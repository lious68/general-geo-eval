"""Ernie _wait_for_response 完成判定自检（fake page，不依赖真实浏览器）。

验证：文心"深度思考"模式先流式输出"正在思考中"+思维链，再出最终答案。
旧实现靠 [class*='thinking']/[class*='loading'] CSS 选择器等"思考指示器"消失——
文心类名哈希化（如 editable__T7WAW4uW），选择器匹配不到 → is_visible 直接 False →
跳过等待；叠加 _wait_for_text_stability 在思考停顿期（可见文本暂时不变）误判稳定，
会提前返回半截"正在思考中"正文（实测 output/webchat_task3_20260620_222419.json
q17="...正在思考中...买到高"、q18="...正在思考中...**阿" 均被截断）。

本测试喂一条"思考中(3次相同)→最终答案(增长→稳定)"的 answerBox 文本序列，
断言 _wait_for_response 返回时最后读到的正文不再含进行中标记"正在思考中"。
旧实现应在思考停顿期因长度稳定提前返回（正文仍含标记）→ FAIL。
"""
import sys
import os
import io
import asyncio

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


# ── fake：覆盖 _wait_for_response / _wait_for_text_stability 用到的 page 接口 ──
class _FakeLocator:
    """locator(sel).last/.first.wait_for/.is_visible 全部立即返回。"""

    @property
    def last(self):
        return self

    @property
    def first(self):
        return self

    async def wait_for(self, state="visible", timeout=0):
        return None

    async def is_visible(self, timeout=0):
        # 无 thinking 元素 → 旧实现的 is_visible 分支判 False、跳过等待思考结束
        return False


# 基类 _wait_for_text_stability 的长度探针 JS 含 "return 0"（空时返回 0）；
# 内容探针返回字符串。用此区分返回类型，避免 str/int 比较报错。
_LENGTH_PROBE_MARKER = "return 0"


class _FakePage:
    """evaluate 按序返回预设 answerBox 文本（墙钟无关，由调用次数推进）。

    - 长度探针（基类 _wait_for_text_stability，JS 含 'return 0'）→ 返回 len(text)
    - 内容探针（返回 innerText）→ 返回 text
    returned 始终记录"该次探针对应的 answerBox 文本"，供断言统一检查标记。
    """

    def __init__(self, text_seq):
        self._seq = list(text_seq)
        self._i = 0
        self.returned = []   # 每次 evaluate 时 answerBox 的文本（与返回类型无关）
        self._loc = _FakeLocator()

    def locator(self, selector):
        return self._loc

    async def evaluate(self, js, arg=None):
        if self._i < len(self._seq):
            text = self._seq[self._i]
            self._i += 1
        else:
            text = self._seq[-1] if self._seq else ""
        self.returned.append(text)
        if _LENGTH_PROBE_MARKER in (js or ""):
            return len(text)
        return text


# 真实截断样本（output/...222419.json q17）：思考中正文，"高"字处截断
THINKING = "参考14个网页\n正在思考中\n\n斗战神官在问哪里能买到高"
ANSWER1 = "参考14个网页\n\n可以从 UCloud、阿里云等厂商购买高性价比 4090 GPU 服务器"
ANSWER2 = ("参考14个网页\n\n可以从 UCloud、阿里云等厂商购买高性价比 4090 GPU 服务器。"
           "具体看预算和用途。")


async def main():
    from web_chat_clients import ErnieWebChatClient

    c = ErnieWebChatClient("ernie")

    # 序列：3 次思考中（旧 _wait_for_text_stability 会在第 3 次因长度稳定提前返回）
    #       → 最终答案增长 → 稳定
    seq = [THINKING, THINKING, THINKING, ANSWER1, ANSWER2, ANSWER2, ANSWER2]
    page = _FakePage(seq)

    # 让被测方法内的 asyncio.sleep 瞬时返回，测试由 evaluate 调用次数驱动（确定性）
    _real_sleep = asyncio.sleep

    async def _noop(_d):
        return None

    asyncio.sleep = _noop
    try:
        # _wait_for_response 返回 None（内部 await _wait_for_text_stability 未取返回值），
        # 这是当前实现约定（与 deepseek/doubao 等子类一致）；判据改为"末次正文无进行中标记"。
        await c._wait_for_response(page, timeout=180)
    finally:
        asyncio.sleep = _real_sleep

    last_text = page.returned[-1] if page.returned else ""
    assert "正在思考中" not in last_text, (
        f"返回时正文仍含进行中标记'正在思考中'（思考未结束就提前返回）：{last_text!r}"
    )
    # 应推进到无标记的最终答案阶段（思考阶段之后读过无标记正文）
    assert any("正在思考中" not in t for t in page.returned[3:]), \
        "应推进到无进行中标记的最终答案阶段"

    print("✅ PASS: Ernie _wait_for_response 等到思考结束（正文无'正在思考中'标记）才返回")


if __name__ == "__main__":
    asyncio.run(main())
