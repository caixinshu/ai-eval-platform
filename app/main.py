"""
FastAPI HTTP 接口

启动:
    uvicorn app.main:app --reload

接口:
    GET  /health   健康检查
    POST /ask      问答接口 {"question": "..."}
    GET  /stats    知识库统计
"""
import sys
from pathlib import Path

# 确保项目根在 sys.path（直接运行时）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from pydantic import BaseModel

from app.rag import ask, get_collection_stats

app = FastAPI(title="AI QA Service", version="1.0.0")


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats():
    return get_collection_stats()


@app.post("/ask")
def ask_api(req: AskRequest):
    return ask(req.question)
