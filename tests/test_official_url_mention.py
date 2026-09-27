"""Official-URL-only answers count as a brand mention; lookalike domains do not."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, 'core'), os.path.join(ROOT, 'backend')]

from analyzer import ResponseAnalyzer  # noqa: E402


def analyze(text):
    return ResponseAnalyzer().analyze('q1', 'qwen', 'qwen', text)


def test_official_url_only_counts_as_mention():
    r = analyze('训练集群需要 InfiniBand 或 RoCE v2 高速网络 \nwww.ucloud.cn\n。普通以太网无法承受。')
    assert r.ucloud_mentioned and r.ucloud_mention_count == 1
    assert r.ucloud_mentions[0].mention_type == 'official_url'


def test_url_only_mention_has_no_rank_recommendation_and_neutral_sentiment():
    # "建议" sits next to the URL and 阿里云 comes later: neither may turn into rank 1 / recommended.
    r = analyze('建议选择支持 RoCE v2 高速网络的服务商 \nwww.ucloud.cn\n。强烈推荐性价比高的方案，阿里云、腾讯云都可以。')
    assert r.ucloud_mentioned
    assert r.ucloud_rank is None
    assert not r.ucloud_recommended and r.ucloud_recommendation_strength == 'none'
    assert r.sentiment_score == 0.5 and r.sentiment_label == 'neutral'
    assert r.position_weight == 0.0


def test_prose_mention_still_ranks():
    r = analyze('推荐 UCloud，其次阿里云。')
    assert r.ucloud_rank == 1


def test_official_subdomain_with_scheme_counts():
    assert analyze('参考文档 https://docs.ucloud.cn/uhost/introduction 。').ucloud_mentioned


def test_lookalike_domains_do_not_count():
    for text in ('单机性价比极高 \nwww.ykucloud.com\n。', '见 www.cosmos-ucloud.com.cn 。', '见 https://www.bestgpucloud.com/gpu 。'):
        assert not analyze(text).ucloud_mentioned, text


def test_prose_mentions_unchanged_when_url_also_present():
    r = analyze('推荐 UCloud 优刻得的 GPU 云主机，详见 https://www.ucloud.cn 。')
    assert r.ucloud_mentioned
    assert all(m.mention_type != 'official_url' for m in r.ucloud_mentions)


def test_no_brand_no_url_not_mentioned():
    assert not analyze('可以考虑阿里云、腾讯云和 AWS。').ucloud_mentioned
