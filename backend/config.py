"""后端配置：全部从环境变量读取，默认值保证本地零配置可跑"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本地默认 SQLite（零依赖启动）；生产用 DATABASE_URL=postgresql://user:pwd@host:5432/db
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(BASE_DIR, "data", "eval_platform.db"),
)

API_TITLE = "AI 问答评测平台 API"
API_VERSION = "v1"

# 评测并发数：本地 SQLite 与向量库都不是高并发场景，默认 3
EVAL_CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "3"))

# 单次评测整体超时（秒）：默认 30 分钟，超时自动置 failed，避免前端无限轮询
EVAL_TIMEOUT_SECONDS = int(os.getenv("EVAL_TIMEOUT_SECONDS", "1800"))

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
