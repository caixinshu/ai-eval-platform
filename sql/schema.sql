-- 评测平台结果存储结构（Day 12 设计，Day 13 报告层对接）
-- 目标库：PostgreSQL 12+（JSONB 存指标明细，天然适合评测数据）

-- 评测任务表：一次评测 = 一行
CREATE TABLE IF NOT EXISTS eval_runs (
    id             VARCHAR(36) PRIMARY KEY,          -- run_id (uuid)
    prompt_version VARCHAR(20)  NOT NULL,            -- 被测 Prompt 版本
    dataset_name   VARCHAR(100) NOT NULL,            -- golden / adversarial / edge
    model_name     VARCHAR(100),                     -- 被测模型
    judge_model    VARCHAR(100),                     -- 裁判模型
    total_cases    INT,
    total_score    DECIMAL(5, 2),
    status         VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running / done / failed
    started_at     TIMESTAMP DEFAULT NOW(),
    finished_at    TIMESTAMP
);

-- 用例结果表：一条用例 = 一行，指标用 JSONB 便于指标迭代
CREATE TABLE IF NOT EXISTS eval_results (
    id           BIGSERIAL PRIMARY KEY,
    run_id       VARCHAR(36) NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id      VARCHAR(50) NOT NULL,
    question     TEXT,
    answer       TEXT,
    contexts     JSONB,        -- 检索到的上下文片段
    metrics      JSONB,        -- 各指标分数（规则/语义/Judge/RAG 四维）
    rule_details JSONB,        -- 规则检查逐项明细
    passed       BOOLEAN,
    duration_ms  INT,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- 索引：按任务查结果、按任务筛失败用例
CREATE INDEX IF NOT EXISTS idx_results_run ON eval_results (run_id);
CREATE INDEX IF NOT EXISTS idx_results_passed ON eval_results (run_id, passed);
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON eval_runs (dataset_name, prompt_version);
