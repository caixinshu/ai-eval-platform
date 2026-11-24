# AI 问答评测平台 · 生产镜像
# 构建：docker build -t ai-eval-platform .
# 运行：docker compose up -d --build
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    ANONYMIZED_TELEMETRY=False \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# gcc/libpq-dev 供 psycopg2 等依赖编译；curl 供健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 应用依赖 + 后端依赖（含 PostgreSQL 驱动）
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r backend/requirements.txt

COPY . .

EXPOSE 8000

# 首次启动要建表，start-period 留足模型下载时间
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
