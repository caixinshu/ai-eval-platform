-- ============================================================
-- 线上反馈与抽样评测表（Day 24，PostgreSQL）
-- 开发库由 SQLAlchemy 自动建表；生产执行本文件
-- ============================================================

CREATE TABLE IF NOT EXISTS user_feedback (
    id              VARCHAR(36) PRIMARY KEY,
    request_id      VARCHAR(64) NOT NULL,
    question        TEXT,
    answer          TEXT,
    rating          VARCHAR(10) NOT NULL,          -- good / bad
    reason          VARCHAR(50),                   -- 不准确/不相关/太啰嗦/有害
    comment         TEXT,
    issue_category  VARCHAR(30),                   -- hallucination/irrelevant/incomplete/format/tone/other
    user_id         VARCHAR(64),
    biz_line        VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_rating_created
    ON user_feedback(rating, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_request
    ON user_feedback(request_id);

CREATE TABLE IF NOT EXISTS online_samples (
    id          VARCHAR(36) PRIMARY KEY,
    request_id  VARCHAR(64) NOT NULL,
    question    TEXT,
    answer      TEXT,
    score       DECIMAL(5, 2) NOT NULL,            -- 0-100
    biz_line    VARCHAR(50),
    latency_ms  INT,
    sampled_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sample_sampled_at ON online_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_sample_request ON online_samples(request_id);
