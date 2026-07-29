"""analyzer 品牌提及口径自检：弱信号词(products/flagship)单独出现不应判为提及。

回归用例：q035/q036 qwen 仅命中「全球加速」「OpenClaw」(flagship)，无本体词，
旧口径误判 mentioned=True，应修正为 False。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from analyzer import ResponseAnalyzer
from brand_profile import default_brand_profile

a = ResponseAnalyzer(brand_profile=default_brand_profile())


def analyze(content):
    from analyzer import AnalysisResult
    r = AnalysisResult(question_id="t", model_key="t", model_name="t")
    r.raw_content = content
    a._detect_brand_mentions(content, r)
    return r


cases = [
    # (描述, 正文, 期望mentioned, 期望含本体词)
    ("仅泛词全球加速(无本体)", "推荐支持全球加速节点的服务器，跨国传输", False),
    ("仅OpenClaw噪声(无本体)", "openclaw养成记 懒人版AI工具清单 销售工作", False),
    ("仅EIP(无本体)", "EIP弹性公网IP是云厂商标配", False),
    ("仅CloudWatch(无本体,AWS产品)", "用CloudWatch监控", False),
    ("本体UCloud", "推荐UCloud海外云主机", True),
    ("本体优刻得", "优刻得性价比高", True),
    ("本体+产品", "UCloud的US3对象存储很好", True),
    ("本体+旗舰", "UCloud星图平台不错", True),
    ("仅UCloudStack(aliases)", "UCloudStack混合云", True),
    ("仅快杰型(产品,无本体)", "快杰型云主机性能强", False),  # 产品词单独出现不算(避免歧义)
]

failed = 0
for desc, content, expected in cases:
    r = analyze(content)
    ok = r.ucloud_mentioned == expected
    print(f"{'✅' if ok else '❌'} {desc}: mentioned={r.ucloud_mentioned} (期望{expected})")
    if not ok:
        failed += 1

print()
if failed:
    print(f"❌ FAIL: {failed} 个用例未通过")
    sys.exit(1)
else:
    print("✅ PASS: 提及口径全部正确")
