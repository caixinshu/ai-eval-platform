"""路由公共工具：统一分页与错误体"""
from fastapi import HTTPException

from backend.config import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX


def api_error(status_code: int, code: str, message: str):
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def page_params(page: int, page_size: int):
    if page < 1:
        api_error(400, "INVALID_PARAM", "page 从 1 开始")
    if page_size < 1 or page_size > PAGE_SIZE_MAX:
        api_error(400, "INVALID_PARAM", "page_size 需在 1-%d 之间" % PAGE_SIZE_MAX)
    return page, page_size or PAGE_SIZE_DEFAULT


def paginate(query, page: int = 1, page_size: int = PAGE_SIZE_DEFAULT) -> dict:
    page, page_size = page_params(page, page_size)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}
