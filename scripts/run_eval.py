"""
统一的评测入口（Day 22 配套）

把「跑一批评测 → 生成门禁可读的 JSON」收敛成一个命令，供 CI 调用：
    python scripts/run_eval.py --dataset golden --limit 20 --output reports/gate-result.json

输出字段固定：metrics（0-1）、total_score（0-100）、latency、prompt_version 等，
quality_gate.py 直接消费，不再为不同报告格式写适配层；case_results 提供逐用例
结果（单条得分 = safety/format/length/correctness 均值 ×100），供 Prompt 版本 diff。

说明：
- 黄金集有 ground_truth：走语义指标（无 LLM Key 时自动降级规则实现）+ 规则指标
- 对抗集 / 边界集没有 ground_truth：走断言评测，assertion_pass_rate 同时作为
  correctness（行为正确率），供发布门禁判断
- performance = 1 - 平均延迟 / 3000ms，与看板、综合评分器口径一致
- 默认不读缓存：CI 要看到本次代码的真实表现，缓存会把回归掩盖掉
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

BUILTIN_DATASETS = {
    "golden": "eval_datasets/golden_set.json",
    "adversarial": "eval_datasets/adversarial_set.json",
    "edge": "eval_datasets/edge_set.json",
}

LATENCY_WORST_MS = 3000.0


def load_cases(dataset: str) -> list:
    """按名称或路径加载数据集，补齐缺失的 id"""
    path = Path(dataset)
    if not path.exists():
        if dataset not in BUILTIN_DATASETS:
            raise ValueError("未知数据集 %s，可选：%s 或直接传 JSON 路径"
                             % (dataset, ", ".join(BUILTIN_DATASETS)))
        path = PROJECT_ROOT / BUILTIN_DATASETS[dataset]

    with open(path, encoding="utf-8") as f:
        cases = json.load(f)
    for index, case in enumerate(cases, 1):
        case.setdefault("id", "case_%03d" % index)
        case.setdefault("question", "")

    # 回流用例先标 verified=false，人工补 ground_truth 后才允许进评测/门禁
    unverified = sum(1 for case in cases if case.get("verified") is False)
    if unverified:
        cases = [case for case in cases if case.get("verified") is not False]
        print("跳过 %d 条未验证（verified=false）的回流用例" % unverified)
    return cases


def _default_qa(case: dict) -> dict:
    """默认被测应用；延迟导入避免 --help 就加载 embedding 模型"""
    from app.rag import ask

    return ask(case["question"])


def collect(cases: list, qa_func=None, prompt_version: str = "ci",
            concurrency: int = 5) -> list:
    """并发跑完一批评测，返回与输入同序的问答结果（含单条耗时）"""
    from engine.runner import EvalRunner

    qa_func = qa_func or _default_qa
    runner = EvalRunner(concurrency=concurrency)
    results = asyncio.run(
        runner.run(cases, qa_func, prompt_version, use_cache=False))

    precomputed = []
    for case, result in zip(cases, results):
        data = result.data or {}
        precomputed.append({
            "question": case["question"],
            "answer": data.get("answer", ""),
            "contexts": data.get("contexts", []),
            "ground_truth": case.get("ground_truth", ""),
            "error": None if result.success else (result.error or "未知错误"),
            "duration_ms": round((result.duration or 0.0) * 1000, 1),
        })
    return precomputed


def _latency_stats(precomputed: list) -> dict:
    values = sorted(item["duration_ms"] for item in precomputed)
    if not values:
        return {"avg_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    p95_index = min(len(values) - 1, int(round(len(values) * 0.95)) - 1)
    return {
        "avg_ms": round(sum(values) / len(values), 1),
        "p95_ms": round(values[max(0, p95_index)], 1),
        "max_ms": round(values[-1], 1),
    }


def build_report(cases: list, precomputed: list, dataset_label: str,
                 prompt_version: str, model: str = "",
                 use_semantic: bool = True) -> dict:
    """把问答结果算成门禁报告（纯计算，qa 结果由 collect 注入，便于测试）"""
    from evaluation.rule_eval import run_rule_eval, run_rule_eval_single

    metrics = {}
    engine = "rule"
    has_ground_truth = any(case.get("ground_truth") for case in cases)

    if has_ground_truth and use_semantic:
        from evaluation.ragas_eval import run_ragas_eval

        ragas = run_ragas_eval(cases, precomputed=precomputed)
        metrics.update({
            "faithfulness": ragas["faithfulness"],
            "answer_relevance": ragas["answer_relevancy"],
            "context_precision": ragas["context_precision"],
            "context_recall": ragas["context_recall"],
        })
        engine = ragas.get("engine", "rule")

    rule = run_rule_eval(cases, precomputed=precomputed)
    metrics.update({
        "correctness": rule["correctness"],
        "safety": rule["safety"],
        "format": rule["format"],
    })

    # 逐用例结果：Prompt 版本对比需要知道具体哪条变好/变差，而不只是均值
    case_results = []
    score_keys = ("safety", "format", "length", "correctness")
    for case, item in zip(cases, precomputed):
        rule_scores = run_rule_eval_single(
            item["answer"], item.get("ground_truth", ""), case.get("question", ""))
        values = [rule_scores[key] for key in score_keys if key in rule_scores]
        case_results.append({
            "case_id": case["id"],
            "question": case["question"],
            "category": case.get("category", ""),
            "answer": item["answer"][:300],
            "total_score": round(sum(values) / len(values) * 100, 2) if values else 0.0,
            "metrics": rule_scores,
            "error": item["error"],
        })

    assertion = None
    if not has_ground_truth:
        from evaluation.assertion_eval import run_assertion_eval

        assertion = run_assertion_eval(cases, precomputed)
        metrics["assertion_pass_rate"] = assertion["pass_rate"]
        # 无标准答案时，行为断言通过率就是这次评测的「正确性」
        metrics["correctness"] = assertion["pass_rate"]

    latency = _latency_stats(precomputed)
    metrics["performance"] = round(
        max(0.0, 1.0 - latency["avg_ms"] / LATENCY_WORST_MS), 4)

    if has_ground_truth:
        from metrics.scorer import compute_composite_score

        total_score = compute_composite_score(metrics, preset="default")["total"]
    else:
        # 对抗/边界集：安全一票否决，其余看断言通过率
        total_score = (0.0 if rule["safety"] < 1.0
                       else round(assertion["pass_rate"] * 100, 2))

    from metrics.scorer import grade

    report = {
        "run_at": datetime.now().isoformat(),
        "dataset": dataset_label,
        "case_count": len(cases),
        "prompt_version": prompt_version,
        "model": model,
        "engine": engine,
        "metrics": {key: round(value, 4) for key, value in metrics.items()},
        "latency": latency,
        "avg_latency_ms": latency["avg_ms"],
        "total_score": total_score,
        "grade": grade(total_score),
        "app_error_count": sum(1 for item in precomputed if item["error"]),
        "case_results": case_results,
        "error_cases": [
            {"question": item["question"], "error": item["error"]}
            for item in precomputed if item["error"]
        ][:20],
    }
    if assertion is not None:
        report["assertion"] = {
            "pass_rate": assertion["pass_rate"],
            "passed": assertion["passed"],
            "failed": assertion["failed"],
            "total": assertion["total"],
        }
    return report


def run_suite(dataset: str = "golden", limit: int = None,
              prompt_version: str = "ci", concurrency: int = 5,
              qa_func=None, use_semantic: bool = True,
              warmup: bool = True) -> dict:
    """完整流程：加载 → 预热 → 并发问答 → 计算指标，返回报告

    warmup：首次调用要加载 embedding 模型（本机约 2-3 分钟），若计入延迟，
    performance 会被冷启动拖到 0；先跑一条不计分的预热，再开始计时。
    """
    cases = load_cases(dataset)
    if limit:
        cases = cases[:limit]
    if not cases:
        raise ValueError("数据集为空: %s" % dataset)

    runner_qa = qa_func or _default_qa
    if warmup:
        print("预热模型（不计入延迟）...")
        start = time.time()
        try:
            runner_qa(cases[0])
            print("预热完成，耗时 %.1fs" % (time.time() - start))
        except Exception as exc:        # 预热失败让正式评测暴露真实错误
            print("[WARN] 预热失败: %s: %s" % (type(exc).__name__, exc))

    precomputed = collect(cases, qa_func=runner_qa,
                          prompt_version=prompt_version,
                          concurrency=concurrency)
    return build_report(cases, precomputed, dataset,
                        prompt_version, use_semantic=use_semantic)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description="跑一批评测并输出门禁报告")
    parser.add_argument("--dataset", default="golden",
                        help="golden / adversarial / edge 或数据集 JSON 路径")
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 条（PR 冒烟建议 20）")
    parser.add_argument("--prompt-version", default="ci",
                        help="本次评测使用的 Prompt 版本（写进报告）")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--output", default="reports/gate-result.json")
    parser.add_argument("--min-assertion", type=float, default=None,
                        help="断言通过率下限（对抗/边界集发布门禁用）")
    parser.add_argument("--no-semantic", action="store_true",
                        help="跳过语义指标，只跑规则/断言")
    args = parser.parse_args(argv)

    report = run_suite(args.dataset, args.limit, args.prompt_version,
                       args.concurrency, use_semantic=not args.no_semantic)

    try:
        from app.rag import get_collection_stats

        stats = get_collection_stats()
        report["model"] = stats.get("llm_model", "")
        report["knowledge_base"] = stats
    except Exception as exc:            # 模型/知识库不可用不影响指标落盘
        print("[WARN] 知识库信息读取失败: %s" % exc)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print("数据集: %s（%d 条）" % (report["dataset"], report["case_count"]))
    print("综合得分: %s/100  %s" % (report["total_score"], report["grade"]))
    for key, value in report["metrics"].items():
        print("  %-20s %.4f" % (key, value))
    print("平均延迟: %.1fms  P95: %.1fms"
          % (report["latency"]["avg_ms"], report["latency"]["p95_ms"]))
    print("报告已保存: %s" % output)

    if args.min_assertion is not None:
        pass_rate = report.get("assertion", {}).get("pass_rate")
        if pass_rate is None:
            print("[ERROR] 该数据集没有断言结果，无法检查 --min-assertion")
            return 2
        if pass_rate < args.min_assertion:
            print("❌ 断言通过率 %.3f < 要求 %.2f"
                  % (pass_rate, args.min_assertion))
            return 1
        print("✅ 断言通过率 %.3f ≥ %.2f" % (pass_rate, args.min_assertion))
    return 0


if __name__ == "__main__":
    sys.exit(main())
