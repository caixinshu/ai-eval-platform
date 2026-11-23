"""
评测执行服务（Day 17：异步任务调度）

后台任务里跑完整评测，长任务不影响接口响应：
- 并发执行：复用 EvalRunner（asyncio.Semaphore），单条失败不中断整批
- 进度上报：每完成一条更新 progress，每 5 条提交一次，前端轮询可见
- 取消：前端置 eval_runs.cancel_requested，执行循环每处理一条检查一次
- 超时：整体超过 EVAL_TIMEOUT_SECONDS 自动置 failed，避免前端无限转圈
- 重启恢复：应用启动时把上次残留的 running 任务统一置 failed，提示重跑
"""
import time
from collections import defaultdict
from datetime import datetime

from backend import config, database
from backend.models.dataset import TestCase
from backend.models.run import EvalResult, EvalRun, MetricSnapshot
from engine.runner import EvalRunner
from evaluation.rule_evaluator import RuleEvaluator

_rule_evaluator = RuleEvaluator()

# 每处理多少条提交一次事务：进度条够实时，又不至于每条都刷盘
COMMIT_EVERY = 5


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


def _evaluate_case(case, answer: str, contexts: list, error: str,
                   use_semantic: bool) -> tuple:
    """单条评分：规则 + 可选语义，返回 (落库回答, metrics, 规则明细, 是否通过, 分数)"""
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
    return answer, metrics, rule["details"], passed, score


async def execute_eval(run_id: str, qa_func=None, use_semantic: bool = True,
                       use_cache: bool = False) -> None:
    """执行一次评测（由 BackgroundTasks 调起，并发跑完后落库）

    qa_func 运行在线程池里（asyncio.to_thread），数据库读写都在事件循环内，
    因此可以安全复用同一个 Session。
    """
    qa_func = qa_func or ask_question
    db = database.SessionLocal()
    state = {
        "processed": 0,          # 已落库的用例数
        "failed": 0,
        "scores": [],
        "metric_sums": defaultdict(float),
        "metric_counts": defaultdict(int),
        "timed_out": False,
        "cancelled": False,
    }
    try:
        run = db.get(EvalRun, run_id)
        if run is None:
            return

        db_cases = db.query(TestCase).filter_by(dataset_id=run.dataset_id).all()
        case_map = {case.id: case for case in db_cases}
        # 引擎只依赖 id/question，传轻量 dict，避免把 ORM 对象带进线程池
        cases = [{"id": case.id, "question": case.question} for case in db_cases]
        total = len(cases)

        run.status = "running"
        run.total_cases = total
        db.commit()

        deadline = time.time() + config.EVAL_TIMEOUT_SECONDS

        def should_stop() -> bool:
            """每处理一条检查一次：超时或用户取消则中止后续用例"""
            if state["timed_out"] or state["cancelled"]:
                return True
            if time.time() >= deadline:
                state["timed_out"] = True
                return True
            # 用独立短会话读取消标记，避免影响主会话里尚未提交的进度
            check_db = database.SessionLocal()
            try:
                fresh = check_db.get(EvalRun, run_id)
                if fresh is not None and fresh.cancel_requested:
                    state["cancelled"] = True
                    return True
                return False
            finally:
                check_db.close()

        async def on_result(result) -> None:
            """每完成一条：评分 → 写结果 → 推进度（每 5 条提交一次）"""
            if result.skipped:          # 取消/超时后未执行的用例，不写结果
                return
            case = case_map.get(result.case_id)
            if case is None:
                return

            data = result.data or {}
            answer = data.get("answer", "")
            contexts = data.get("contexts", [])
            error = "" if result.success else (result.error or "未知错误")

            answer, metrics, rule_details, passed, score = _evaluate_case(
                case, answer, contexts, error, use_semantic)
            state["scores"].append(score)
            if not passed:
                state["failed"] += 1
            for key, value in metrics.items():
                state["metric_sums"][key] += value
                state["metric_counts"][key] += 1

            db.add(EvalResult(
                run_id=run_id, case_id=case.id, question=case.question,
                answer=answer, contexts=contexts, metrics=metrics,
                rule_details=rule_details, passed=passed,
                duration_ms=int((result.duration or 0) * 1000),
            ))
            state["processed"] += 1
            run.progress = min(99, int(state["processed"] / max(1, total) * 100))
            if state["processed"] % COMMIT_EVERY == 0 or state["processed"] == total:
                db.commit()

        runner = EvalRunner(concurrency=config.EVAL_CONCURRENCY)
        await runner.run(cases, qa_func, run.prompt_version,
                         on_result=on_result, should_stop=should_stop,
                         use_cache=use_cache)

        for key, value in state["metric_sums"].items():
            db.add(MetricSnapshot(
                run_id=run_id, metric_name=key,
                value=round(value / max(1, state["metric_counts"][key]), 4)))

        # 终态：超时 > 取消 > 正常完成
        if state["timed_out"]:
            run.status = "failed"
            run.error_message = ("评测超时（超过 %d 秒），已中止；"
                                 "请缩小数据集或调大 EVAL_TIMEOUT_SECONDS 后重跑"
                                 % config.EVAL_TIMEOUT_SECONDS)
        elif state["cancelled"]:
            run.status = "cancelled"
        else:
            run.status = "done"
            run.progress = 100
        if state["scores"]:
            run.total_score = round(
                sum(state["scores"]) / len(state["scores"]), 2)
        run.finished_at = datetime.now()
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            run = db.get(EvalRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error_message = "%s: %s" % (type(exc).__name__, exc)
                run.finished_at = datetime.now()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def recover_stale_runs() -> int:
    """应用启动时恢复：上次进程退出时仍在 running 的任务不可能再继续，统一置 failed

    否则前端会永远轮询一个不会前进的进度条。
    """
    db = database.SessionLocal()
    try:
        stale = db.query(EvalRun).filter(EvalRun.status == "running").all()
        for run in stale:
            run.status = "failed"
            run.error_message = "服务重启导致任务中断，请重新发起评测"
            run.finished_at = datetime.now()
        db.commit()
        return len(stale)
    finally:
        db.close()
