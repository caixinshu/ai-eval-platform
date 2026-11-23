-- ============================================================
-- AI 问答评测平台 · 完整数据库 Schema（Day 15）
-- 目标库：PostgreSQL 12+（JSONB 存指标/上下文，避免频繁改表）
-- 设计要点：先定契约再写代码；所有表带外键与级联删除；常用查询路径建索引
-- ============================================================

-- 1. 数据集：一次入库 = 一个数据集版本
CREATE TABLE IF NOT EXISTS datasets (
    id          VARCHAR(36) PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    type        VARCHAR(20)  NOT NULL,               -- golden / edge / adversarial
    description TEXT,
    case_count  INT DEFAULT 0,
    version     VARCHAR(20) DEFAULT 'v1',
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (name, version)                           -- 同名数据集允许多版本
);

-- 2. 用例：一条测试问题
CREATE TABLE IF NOT EXISTS test_cases (
    id                VARCHAR(50) PRIMARY KEY,       -- 如 golden_001
    dataset_id        VARCHAR(36) NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    question          TEXT NOT NULL,
    ground_truth      TEXT,
    category          VARCHAR(50),
    difficulty        VARCHAR(20),                   -- easy / medium / hard
    tags              JSONB,                         -- ["退款", "政策"]
    expected_behavior JSONB,                         -- 对抗/边界集的断言规则
    expected_context  JSONB,                         -- 期望召回的知识片段（算 Recall 用）
    created_at        TIMESTAMP DEFAULT NOW()
);

-- 3. Prompt 版本：一次修改 = 一条新记录，不可覆盖
CREATE TABLE IF NOT EXISTS prompt_versions (
    id          VARCHAR(36) PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    version     VARCHAR(20)  NOT NULL,
    content     TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (name, version)
);

-- 4. 评测任务：一次评测 = 一行，status/progress 支持前端轮询
CREATE TABLE IF NOT EXISTS eval_runs (
    id              VARCHAR(36) PRIMARY KEY,
    dataset_id      VARCHAR(36) REFERENCES datasets(id),
    prompt_version  VARCHAR(20) NOT NULL,
    model_name      VARCHAR(100),
    judge_model     VARCHAR(100),
    status          VARCHAR(20) DEFAULT 'pending',   -- pending/running/done/failed/cancelled
    cancel_requested BOOLEAN DEFAULT FALSE,          -- 取消标记：执行循环逐条检查后中止
    progress        INT DEFAULT 0,                   -- 0-100，前端进度条
    total_cases     INT,
    total_score     DECIMAL(5, 2),
    error_message   TEXT,                            -- 失败原因（不吞异常）
    started_at      TIMESTAMP DEFAULT NOW(),
    finished_at     TIMESTAMP
);

-- 5. 用例结果：一条用例 = 一行
CREATE TABLE IF NOT EXISTS eval_results (
    id           BIGSERIAL PRIMARY KEY,
    run_id       VARCHAR(36) NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id      VARCHAR(50) NOT NULL,
    question     TEXT,
    answer       TEXT,
    contexts     JSONB,                              -- 检索片段
    metrics      JSONB,                              -- 各指标分数
    rule_details JSONB,                              -- 规则检查逐项明细
    passed       BOOLEAN,
    duration_ms  INT,
    created_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE (run_id, case_id)                         -- 同一任务内用例不可重复
);

-- 6. 指标快照：按指标展开，供趋势图/雷达图直接查询
--    与 eval_results.metrics 冗余，但避免可视化时解析整段 JSONB
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    run_id      VARCHAR(36) NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    metric_name VARCHAR(50) NOT NULL,                -- faithfulness / context_recall ...
    value       DECIMAL(8, 4) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (run_id, metric_name)
);

-- ---------- 索引：覆盖「按数据集查用例」「按任务查结果/失败项」「按指标做趋势」 ----------
CREATE INDEX IF NOT EXISTS idx_cases_dataset      ON test_cases (dataset_id, category);
CREATE INDEX IF NOT EXISTS idx_runs_dataset       ON eval_runs (dataset_id, prompt_version);
CREATE INDEX IF NOT EXISTS idx_runs_status        ON eval_runs (status);
CREATE INDEX IF NOT EXISTS idx_results_run        ON eval_results (run_id);
CREATE INDEX IF NOT EXISTS idx_results_failed     ON eval_results (run_id, passed);
CREATE INDEX IF NOT EXISTS idx_snapshots_metric   ON metric_snapshots (metric_name, created_at);
