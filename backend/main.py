"""
FastAPI 应用入口

启动：python -m uvicorn backend.main:app --reload --port 8000
页面：http://localhost:8000/（frontend 静态页）
文档：http://localhost:8000/docs
"""
import mimetypes
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import API_TITLE, API_VERSION, BASE_DIR
from backend.database import init_db
from backend.routers import dashboard, datasets, prompts, runs
from backend.services.eval_service import recover_stale_runs

# Windows 注册表可能把 .js 映射成 text/plain，浏览器会拒绝执行 ES module，这里强制纠正
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 上次进程退出时 running 的任务不可能继续，统一置 failed，避免前端无限轮询
    recover_stale_runs()
    yield


app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)

# 前端本地开发端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    """统一错误体：{code, message}"""
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        body = exc.detail
    else:
        body = {"code": "INTERNAL_ERROR", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": API_VERSION}


app.include_router(datasets.router)
app.include_router(prompts.router)
app.include_router(runs.router)
app.include_router(dashboard.router)

# 前端静态页挂到最后：/api 与 /docs 先匹配，其余交给 frontend/
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "frontend"), html=True),
          name="frontend")
