"""
UCloud GEO 评估框架 - 三级任务调度引擎（任务 → 模型 → 问题）

核心思想：
  - 「单元」（Unit）是唯一事实来源，每单元自带 status；
  - 调度器无状态：每次重新计算「还剩什么」，崩溃重入与首次跑走同一套代码；
  - 防封号三策并用：
      ① 跨模型交错：每模型一个 async worker 并发推进，自然交错各平台请求；
      ② 逐模型限流配额：RateLimiter 突发上限 + 滑动窗口 + 冷却；
      ③ 封号信号检测+自动退避：ThrottledError → 长冷却后退回 pending 重试；
        LoginExpiredError → 该模型剩余单元 skipped（需人工重登）。
  - 单题多次重试：瞬态错误指数退避 + 抖动，超 max_attempts 落 failed。

server（eval_runner.py）与 local（local_webchat_runner.py）共用本引擎，
各自注入 client_factory（webchat 浏览器 / API 客户端）与 on_unit_done 回调。

客户端协议（client_factory 返回的对象需满足）：
  - async initialize() -> bool        （API 客户端可为 no-op 返回 True）
  - async chat(question) -> dict      （返回 {content, error, model_name, ...}）
  - async close() -> None
  - .name: str
  - .is_configured: bool
  webchat 客户端（WebChatClientBase）原生满足；API 客户端在 eval_runner 内做异步适配。
"""
import asyncio
import random
import time
import logging
from collections import deque
from typing import Callable, Awaitable, Dict, List, Optional, Any

from task_units import Unit, UnitStore
from webchat_policy import get_model_policy, classify_signal, BACKOFF

logger = logging.getLogger(__name__)


# ============ 异常 ============

class ThrottledError(Exception):
    """触发限流/风控（频率过快等）。需长冷却后重试。"""


class LoginExpiredError(Exception):
    """登录态失效。需人工重新登录，该模型剩余单元跳过。"""


class TransientError(Exception):
    """瞬态错误（超时/提取失败/通用异常）。按退避重试。"""


# ============ 限流器 ============

class RateLimiter:
    """单模型限流：突发上限 + 滑动窗口配额 + 冷却。

    注意：DeepSeek 等平台的封号看的是「同一账号的连续请求计数」，
    跨模型交错不能降低单账号自身的连续计数——真正抑制封号的是本限流器：
    把单账号短时连发数（max_consecutive）与窗口配额（rate_max）压到阈值以下。
    """

    def __init__(self, model_key: str, policy: dict):
        self.model_key = model_key
        self.policy = policy
        self._timestamps: deque = deque()      # 滑动窗口内请求时间
        self._consecutive = 0                   # 自上次 burst_cooldown 以来的连续计数
        self._cooldown_until = 0.0               # ban/throttle 冷却截止（monotonic）
        self._last_request = 0.0                # 上次请求时刻（monotonic）

    async def acquire(self) -> None:
        """阻塞直到允许发出下一次请求。"""
        pol = self.policy

        # 1) honor cooldown（封号退避）
        now = time.monotonic()
        if now < self._cooldown_until:
            wait = self._cooldown_until - now
            logger.info(f"[LIMIT {self.model_key}] cooldown 等待 {wait:.0f}s")
            await asyncio.sleep(wait)

        # 2) burst cap：连续达上限 → 强制 burst_cooldown 后重置
        if self._consecutive >= pol.get("max_consecutive", 9999):
            logger.info(f"[LIMIT {self.model_key}] 突发上限 {self._consecutive}，"
                        f"冷却 {pol.get('burst_cooldown',0)}s")
            await asyncio.sleep(pol.get("burst_cooldown", 0))
            self._consecutive = 0

        # 3) 滑动窗口配额
        self._prune()
        window = pol.get("rate_window_sec", 3600)
        rate_max = pol.get("rate_max", 9999)
        if len(self._timestamps) >= rate_max:
            wait = window - (time.monotonic() - self._timestamps[0])
            if wait > 0:
                logger.info(f"[LIMIT {self.model_key}] 滑动窗口配额满，等待 {wait:.0f}s")
                await asyncio.sleep(wait)
            self._prune()

        # 4) 相邻请求最小间隔
        delay = pol.get("inter_unit_delay", 0)
        if self._last_request:
            elapsed = time.monotonic() - self._last_request
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)

        now = time.monotonic()
        self._timestamps.append(now)
        self._consecutive += 1
        self._last_request = now

    def enter_cooldown(self, seconds: float) -> None:
        """检测到 throttle 后进入长冷却。"""
        self._cooldown_until = time.monotonic() + seconds
        self._consecutive = 0
        logger.warning(f"[LIMIT {self.model_key}] 进入 {seconds:.0f}s 封号冷却")

    def _prune(self) -> None:
        window = self.policy.get("rate_window_sec", 3600)
        cutoff = time.monotonic() - window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


def compute_backoff(attempts: int) -> float:
    """指数退避 + 抖动。attempts 从 1 起。"""
    b = BACKOFF
    base = min(b["cap"], b["base"] * (b["factor"] ** max(0, attempts - 1)))
    jitter = base * b["jitter"] * random.uniform(-1, 1)
    return max(0.5, base + jitter)


# ============ 调度器 ============

# 回调类型
OnUnitDone = Callable[[Unit, Dict[str, Any]], Awaitable[None]]
OnProgress = Callable[[Dict[str, Any]], Awaitable[None]]
ClientFactory = Callable[[str], Awaitable[Any]]


class EvalScheduler:
    """三级任务调度器。"""

    def __init__(
        self,
        run_id: str,
        models: List[str],
        questions: List[Dict],
        store: UnitStore,
        client_factory: ClientFactory,
        on_unit_done: Optional[OnUnitDone] = None,
        on_progress: Optional[OnProgress] = None,
        extra_policy: Optional[Dict[str, dict]] = None,
        per_model_questions: Optional[Dict[str, List[Dict]]] = None,
    ):
        self.run_id = run_id
        self.models = list(models)
        self.questions = questions
        self.store = store
        self.client_factory = client_factory
        self.on_unit_done = on_unit_done
        self.on_progress = on_progress
        self.extra_policy = extra_policy or {}

        # 每模型限流器
        self.limiters: Dict[str, RateLimiter] = {
            mk: RateLimiter(mk, self._policy_for(mk)) for mk in self.models
        }
        # 每模型独立题区间（v2 配置 units）。缺省 = 所有模型共享 questions（旧行为）。
        self.per_model_questions = per_model_questions
        if per_model_questions:
            # 限流器需覆盖所有出现过的模型
            extra_models = [mk for mk in per_model_questions if mk not in self.models]
            for mk in extra_models:
                self.models.append(mk)
                self.limiters[mk] = RateLimiter(mk, self._policy_for(mk))
            # 题序：所有模型题集的并集
            seen = {}
            for q in questions:
                seen.setdefault(q["id"], q)
            for mk, qs in per_model_questions.items():
                for q in qs:
                    seen.setdefault(q["id"], q)
            self._q_order = {qid: i for i, qid in enumerate(sorted(seen.keys()))}
        else:
            self._q_order = {q["id"]: i for i, q in enumerate(questions)}
        self._total = 0

    def _policy_for(self, model_key: str) -> dict:
        p = get_model_policy(model_key)
        p.update(self.extra_policy.get(model_key, {}))
        return p

    def _question_order(self, qid: str) -> int:
        return self._q_order.get(qid, 1 << 30)

    # ---------- 准备 ----------

    async def prepare(self) -> None:
        """展开单元（幂等）+ 重置残留 running。每模型按各自题区间展开。"""
        model_names = {mk: self._model_name(mk) for mk in self.models}
        if self.per_model_questions:
            total = 0
            for mk in self.models:
                qs = self.per_model_questions.get(mk, self.questions)
                total += self.store.expand_units(
                    self.run_id, [mk], [q["id"] for q in qs],
                    {mk: model_names.get(mk, mk)}
                )
            self._total = total
        else:
            self._total = self.store.expand_units(
                self.run_id, self.models, [q["id"] for q in self.questions], model_names
            )
        reset = self.store.reset_stale_running(self.run_id)
        logger.info(f"[SCHED {self.run_id}] prepared {self._total} units"
                    f"({len(self.models)} models), reset {reset} stale running")

    def _model_name(self, mk: str) -> str:
        for q in self.questions:  # 占位，实际名字由 client 提供
            break
        return mk

    # ---------- 运行 ----------

    async def run(self) -> Dict[str, int]:
        """并发运行所有模型 worker，返回单元状态计数。"""
        await self.prepare()
        await self._emit_progress(force=True)

        workers = [self._model_worker(mk) for mk in self.models]
        await asyncio.gather(*workers, return_exceptions=True)

        counts = self.store.counts(self.run_id)
        logger.info(f"[SCHED {self.run_id}] done: {counts}")
        return counts

    async def _model_worker(self, model_key: str) -> None:
        """单模型 worker：初始化客户端 → 逐题推进。"""
        policy = self._policy_for(model_key)
        limiter = self.limiters[model_key]
        client = None

        try:
            client = await self.client_factory(model_key)
            if client is None:
                logger.warning(f"[SCHED {self.run_id}] {model_key}: 无客户端，跳过该模型")
                self.store.set_model_status(self.run_id, model_key, "skipped")
                await self._emit_progress(force=True)
                return
            if hasattr(client, "is_configured") and not client.is_configured:
                logger.warning(f"[SCHED {self.run_id}] {model_key}: 未配置（无认证/API key），跳过该模型")
                self.store.set_model_status(self.run_id, model_key, "skipped")
                await self._emit_progress(force=True)
                return
            if hasattr(client, "initialize"):
                ok = await client.initialize()
                if not ok:
                    logger.warning(f"[SCHED {self.run_id}] {model_key}: 初始化失败，跳过")
                    self.store.set_model_status(self.run_id, model_key, "skipped")
                    await self._emit_progress(force=True)
                    return
            name = getattr(client, "name", model_key)

            # 预读该模型的问题文本（每模型题区间）
            if self.per_model_questions:
                qs = self.per_model_questions.get(model_key, self.questions)
            else:
                qs = self.questions
            q_text = {q["id"]: q["question"] for q in qs}

            while True:
                if self._all_done_for_model(model_key):
                    break

                unit = self._pick_next(model_key)
                if unit is None:
                    break  # 无 pending（可能在冷却等待中由其他状态占用）

                unit.status = "running"
                unit.attempts = (unit.attempts or 0) + 1
                unit.model_name = name
                self.store.upsert(unit)

                try:
                    response = await self._call_chat_with_limits(
                        client, q_text.get(unit.question_id, ""), model_key, limiter, policy, unit
                    )
                except LoginExpiredError as e:
                    logger.error(f"[SCHED {self.run_id}] {model_key}: 登录失效，整模型跳过 ({e})")
                    unit.last_error = str(e)
                    self.store.upsert(unit)
                    self.store.set_model_status(self.run_id, model_key, "skipped")
                    await self._emit_progress(force=True)
                    if self.on_progress:
                        await self.on_progress({"type": "model_skipped", "model_key": model_key,
                                                "reason": "login_expired"})
                    return
                except ThrottledError as e:
                    logger.warning(f"[SCHED {self.run_id}] {model_key}:{unit.question_id} "
                                   f"触发限流，退回 pending 等 {policy.get('ban_cooldown_sec',0)}s 冷却")
                    unit.last_error = str(e)
                    unit.status = "pending"
                    self.store.upsert(unit)
                    limiter.enter_cooldown(policy.get("ban_cooldown_sec", 900))
                    if self.on_progress:
                        await self.on_progress({"type": "throttled", "model_key": model_key,
                                                "question_id": unit.question_id})
                    continue  # 立刻尝试重 pick（acquire 会在冷却上阻塞）
                except Exception as e:
                    # 瞬态：超 max_attempts 落 failed，否则退避重试
                    unit.last_error = str(e)
                    if unit.attempts >= policy.get("max_attempts", 3):
                        unit.status = "failed"
                        self.store.upsert(unit)
                        logger.error(f"[SCHED {self.run_id}] {model_key}:{unit.question_id} "
                                     f"放弃（{unit.attempts} 次）: {str(e)[:120]}")
                        await self._finalize_failed(unit, str(e))
                        continue
                    else:
                        # 关键：重试前必须回退为 pending，否则 _pick_next 不会再选中它
                        unit.status = "pending"
                        self.store.upsert(unit)
                        backoff = compute_backoff(unit.attempts)
                        logger.info(f"[SCHED {self.run_id}] {model_key}:{unit.question_id} "
                                    f"瞬态错误，第 {unit.attempts} 次退避 {backoff:.1f}s 重试")
                        await asyncio.sleep(backoff)
                        continue

                # 成功
                unit.status = "done"
                unit.content = response.get("content", "")
                self.store.upsert(unit)
                if self.on_unit_done:
                    await self.on_unit_done(unit, response)
                await self._emit_progress()

        except asyncio.CancelledError:
            logger.warning(f"[SCHED {self.run_id}] {model_key}: worker 被取消")
            raise
        except Exception as e:
            logger.exception(f"[SCHED {self.run_id}] {model_key}: worker 异常: {e}")
        finally:
            if client is not None and hasattr(client, "close"):
                try:
                    await client.close()
                except Exception as e:
                    logger.warning(f"[SCHED {self.run_id}] {model_key}: close 失败: {e}")

    async def _call_chat_with_limits(self, client, question, model_key, limiter, policy, unit) -> Dict:
        """带限流 + 封号信号检测的单次提问（含瞬态退避内循环）。"""
        max_attempts = policy.get("max_attempts", 3)
        # unit.attempts 在外层已自增；这里从当前 attempts 起再允许 max_attempts 次该题尝试
        # （外层 unit.attempts 统计的是「该题累计尝试数」，瞬态退避后回到这里继续）
        # 实际重试由外层 while + 本函数异常上抛驱动，本函数只做一次「限流→提问→分类」。
        await limiter.acquire()
        response = await self._do_chat(client, question)

        content = response.get("content", "") or ""
        err = response.get("error")
        if err:
            sig = classify_signal(err)
            if sig == "login_expired":
                raise LoginExpiredError(err)
            if sig == "throttle":
                raise ThrottledError(err)
            raise TransientError(err)

        # webchat 客户端已在上游把 throttle/login 编码进 error，上面已处理；
        # 不再对 content 二次扫描，避免「异常/验证」等宽词在正常回答里误伤。

        if not content.strip():
            raise TransientError("empty response")
        return response

    async def _do_chat(self, client, question: str) -> Dict:
        """调用客户端 chat，兼容 async / sync 两种签名。"""
        import inspect
        fn = getattr(client, "chat")
        if inspect.iscoroutinefunction(fn):
            return await fn(question)
        # sync（API ModelClient）→ 放到线程池，避免阻塞事件循环
        return await asyncio.to_thread(fn, question)

    # ---------- 选择 / 计数 ----------

    def _pick_next(self, model_key: str) -> Optional[Unit]:
        """选该模型下一个 pending 单元（按 question 顺序）。"""
        pending = [u for u in self.store.list_pending(self.run_id) if u.model_key == model_key]
        if not pending:
            return None
        pending.sort(key=lambda u: self._question_order(u.question_id))
        return pending[0]

    def _all_done_for_model(self, model_key: str) -> bool:
        """该模型是否已无 pending/running（done/failed/skipped 视为终止）。"""
        counts = self.store.counts(self.run_id)
        # 只要还有 pending 即未完成
        # （running 不应残留，因为 worker 单线程顺序处理）
        pending = [u for u in self.store.list_pending(self.run_id) if u.model_key == model_key]
        return len(pending) == 0

    async def _finalize_failed(self, unit: Unit, error: str) -> None:
        if self.on_unit_done:
            await self.on_unit_done(unit, {"content": "", "error": error,
                                          "model_name": unit.model_name})

    async def _emit_progress(self, force: bool = False) -> None:
        if not self.on_progress:
            return
        counts = self.store.counts(self.run_id)
        completed = counts["done"] + counts["failed"] + counts["skipped"]
        await self.on_progress({
            "type": "progress",
            "run_id": self.run_id,
            "completed": completed,
            "total": self._total,
            "counts": counts,
        })
