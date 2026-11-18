"""结果分析层单元测试（分组统计 / 版本对比 / 聚类小样本分支）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.aggregator import aggregate, group_badcases
from analysis.badcase import _top_terms, cluster_badcases
from analysis.comparator import compare_runs

CASES = [
    {"id": "c1", "category": "退款", "question": "退款多久到账"},
    {"id": "c2", "category": "退款", "question": "怎么申请退款"},
    {"id": "c3", "category": "物流", "question": "怎么查物流"},
]


def test_aggregate_by_category():
    results = [
        {"case_id": "c1", "total_score": 80, "passed": True,
         "metrics": {"faithfulness": 0.9}},
        {"case_id": "c2", "total_score": 40, "passed": False,
         "metrics": {"faithfulness": 0.5}},
        {"case_id": "c3", "total_score": 50, "passed": False,
         "metrics": {"faithfulness": 0.7}},
    ]
    stats = aggregate(results, CASES)
    assert stats["退款"]["count"] == 2
    assert stats["退款"]["avg_score"] == 60.0
    assert stats["退款"]["pass_rate"] == 0.5
    assert list(stats.keys())[0] == "物流", "均分最低的类别排最前"


def test_group_badcases():
    badcases = [
        {"id": "c1", "question": "退款多久到账",
         "failed_metrics": [{"metric": "answer_relevancy", "score": 0, "threshold": 0.3}]},
        {"id": "c2", "question": "怎么申请退款",
         "failed_metrics": [{"metric": "answer_relevancy", "score": 0, "threshold": 0.3},
                            {"metric": "context_recall", "score": 0, "threshold": 0.3}]},
        {"id": "c3", "question": "怎么查物流", "failed_metrics": []},
    ]
    stats = group_badcases(badcases, CASES)
    assert stats["退款"]["count"] == 2
    assert stats["退款"]["top_failed_metrics"][0] == ("answer_relevancy", 2)
    assert stats["物流"]["count"] == 1


def test_group_badcases_empty():
    assert group_badcases([], CASES) == {}


def test_compare_runs_flags_regression():
    baseline = {"metrics": {"correctness": 0.8, "faithfulness": 0.9}, "total_score": 80}
    current = {"metrics": {"correctness": 0.70, "faithfulness": 0.91}, "total_score": 78}
    diff = compare_runs(current, baseline)
    assert diff["metrics"]["correctness"]["improved"] is False
    assert diff["metrics"]["correctness"]["significant"] is True
    assert diff["metrics"]["faithfulness"]["significant"] is False, "1 个点属于噪声"
    assert diff["regressions"] == ["correctness"]
    assert diff["total"]["delta"] == -2


def test_compare_runs_zero_baseline():
    diff = compare_runs({"metrics": {"correctness": 0.5}, "total_score": 50},
                        {"metrics": {}, "total_score": 0})
    assert diff["metrics"]["correctness"]["delta_pct"] == 0


def test_cluster_small_branch():
    badcases = [{"id": "c1", "question": "退款多久到账"},
                {"id": "c2", "question": "怎么查物流"}]
    clusters = cluster_badcases(badcases, n_clusters=5)
    assert len(clusters) == 1
    assert clusters[0]["label"] == "全部"


def test_top_terms_filters_stopwords():
    terms = _top_terms(["怎么修改密码", "忘记密码怎么办"])
    assert "密码" in terms
