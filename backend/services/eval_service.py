"""
评测执行服务

后台任务里跑完整评测：逐条问答 → 规则检查 → 语义正确性 → 落库 → 更新进度。
- 单条失败不影响整批（失败用例 passed=False，回答前缀 [应用异常] 保留原因）
- 指标同时按用例存 metrics，按任务存 metric_snapshots（供趋势图直查）
"""
import time
from collections import defaultdict
from datetime import datetime

from backend import database
from backend.models.dataset import TestCase
from backend.models.run import EvalResult, EvalRun, MetricSnapshot
from evaluation.rule_evaluator import RuleEvaluator

_rule_evaluator = RuleEvaluator()


def ask_question(case: dict) -> dict:
    """默认被测应用；延迟导入避免 API 启动即加载 embedding 模型"""
    from app.rag import ask

    result = ask(case["question"])
    return {"answer": result["answer"], "contexts": result["contexts"]}


def _rule_config(case) -> dict:
    """expected_behavior 里除断言类型外的字段直接作为规则配置"""
    cfg = case.expected_behavior or {}
    return {k: v for k, v in cfg.items()
            if k in ("must_contain", "must_not_contain", "expect_json",
                     "required_fields", "regex_pattern", "require_citation",
                     "min_len", "max_len")}


def _semantic_score(answer: str, ground_truth: str) -> float:
    from evaluation.semantic_evaluator import semantic_similarity

    return float(semantic_similarity(answer, ground_truth))


def execute_eval(run_id: str, qa_func=None, use_semantic: bool = True) -> None:
    """执行一次评测（在后台线程中调用）"""
    qa_func = qa_func or ask_question
    db = database.SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run is None:
            return

        cases = db.query(TestCase).filter_by(dataset_id=run.dataset_id).all()
        run.status = "running"
        run.total_cases = len(cases)
        db.commit()

        metric_sums = defaultdict(float)
        metric_counts = defaultdict(int)
        case_scores = []
        failed = 0

        for index, case in enumerate(cases, 1):
            start = time.time()
            answer, contexts, error = "", [], ""
            try:
                out = qa_func({"id": case.id, "question": case.question}) or {}
                answer = out.get("answer", "")
                contexts = out.get("contexts", [])
            except Exception as exc:                      # 单条失败不中断整批
                error = "%s: %s" % (type(exc).__name__, exc)

            rule = _rule_evaluator.evaluate(answer, _rule_config(case))
            metrics = {"rule_score": rule["rule_score"]}
            if error:
                answer = "[应用异常] " + error       # 保留现场，便于报告直接看到原因
            if use_semantic and case.ground_truth and not error:
                try:
                    metrics["correctness"] = round(
                        _semantic_score(answer, case.ground_truth), 4)
                except Exception:
                    pass

            # 通过线对齐 Day 9 校准的相似度阈值 0.84
            correctness = metrics.get("correctness", 1.0)
            passed = bool(rule["passed"]) and correctness >= 0.84 and not error
            score = round(sum(metrics.values()) / len(metrics) * 100, 2)
            case_scores.append(score)
            if not passed:
                failed += 1

            for key, value in metrics.items():
                metric_sums[key] += value
                metric_counts[key] += 1

            db.add(EvalResult(
                run_id=run_id, case_id=case.id, question=case.question,
                answer=answer, contexts=contexts, metrics=metrics,
                rule_details=rule["details"], passed=passed,
                duration_ms=int((time.time() - start) * 1000),
            ))
            run.progress = int(index / max(1, len(cases)) * 100)
            db.commit()

        for key, total in metric_sums.items():
            db.add(MetricSnapshot(run_id=run_id, metric_name=key,
                                  value=round(total / max(1, metric_counts[key]), 4)))
        run.status = "done"
        run.progress = 100
        run.total_score = round(sum(case_scores) / len(case_scores), 2) if case_scores else 0
        run.finished_at = datetime.now()
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(EvalRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = "%s: %s" % (type(exc).__name__, exc)
            db.commit()
    finally:
        db.close()
