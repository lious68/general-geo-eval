"""品牌档案接口 + 问题生成接口冒烟（TestClient，不真打模型 API）。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())

    import app as appmod
    # 放开鉴权
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/settings", "/api/questions"]
    from routers.auth import require_admin
    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 1. 未设置品牌档案 → configured=False
    r = client.get("/api/settings/brand-profile")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["configured"] is False, r.text
    assert r.json()["data"]["brand_name"] == "UCloud", "默认应回退 UCloud"  # noqa

    # 2. PUT 设置品牌档案（自动派生）
    r = client.put("/api/settings/brand-profile", json={
        "brand_name": "Acme云", "company_name": "阿克米科技",
        "website": "https://www.acme-cloud.cn", "industry": "云计算",
    })
    assert r.status_code == 200, r.text
    prof = r.json()["data"]
    assert prof["brand_name"] == "Acme云", prof
    assert "acme-cloud.cn" in prof["official_domains"], prof
    assert any("acme" in p and "cloud" in p for p in prof["url_patterns"]), prof
    assert prof["display_names"], prof

    # 3. GET 应 configured=True 且品牌缓存已刷新
    r = client.get("/api/settings/brand-profile")
    assert r.json()["data"]["configured"] is True, r.text
    assert db.get_brand_profile().brand_name == "Acme云", "缓存应已刷新"

    # 4. 自然问题判定用新品牌档案
    assert db.is_natural_question("Acme云怎么样？", "") is False, "含品牌词应非自然"
    assert db.is_natural_question("国内云服务器推荐哪家？", "") is True, "不含品牌词应自然"

    # 5. 生成接口：未配 API Key → 400
    r = client.post("/api/questions/generate", json={
        "brand_name": "Acme云", "website": "https://www.acme-cloud.cn",
        "industry": "云计算", "model_key": "deepseek",
    })
    assert r.status_code == 400, r.text
    assert "API Key" in r.text or "未配置" in r.text, r.text

    # 6. 品牌名为空 → 400
    r = client.put("/api/settings/brand-profile", json={"brand_name": "  ", "website": "x"})
    assert r.status_code == 400, r.text

    # 7. 解析器 + 每场景 5 题规整（不依赖网络）
    from question_generator import _parse_questions, _enforce_five_per_scenario
    mock = '''[
      {"category":"海外云主机","question_type":"品牌词","question":"Acme云海外云主机怎么样？","tags":["Acme云"]},
      {"category":"海外云主机","question_type":"品类词","question":"便宜海外VPS推荐哪家？","tags":["海外VPS"]},
      {"category":"海外云主机","question_type":"对比词","question":"Acme云和阿里云哪个好？","tags":["对比"]},
      {"category":"海外云主机","question_type":"场景词","question":"企业出海用什么云？","tags":["出海"]},
      {"category":"海外云主机","question_type":"品类词","question":"海外云主机推荐哪家？","tags":["海外云主机"]},
      {"category":"海外云主机","question_type":"品类词","question":"多余的一题","tags":[]},
      {"category":"GPU","question_type":"品牌词","question":"Acme云GPU怎么样？","tags":["GPU"]}
    ]'''
    items = _parse_questions(mock)
    enforced, counts = _enforce_five_per_scenario(items)
    assert counts["海外云主机"] == 6, counts
    assert counts["GPU"] == 1, counts
    cat_counts = {}
    for it in enforced:
        cat_counts[it["category"]] = cat_counts.get(it["category"], 0) + 1
    assert cat_counts["海外云主机"] == 5, "超过5应截断到5"
    assert cat_counts["GPU"] == 1, "不足5应保留"
    print("✅ PASS: 品牌档案接口 + 问题生成接口 + 解析器规整")


if __name__ == "__main__":
    main()
