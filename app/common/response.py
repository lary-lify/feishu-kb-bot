"""统一响应与业务异常。"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class BusinessError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


def ok(data: Any = None, msg: str = "ok") -> dict:
    return {"code": 0, "msg": msg, "data": data}


def err(message: str, code: int = 1) -> dict:
    return {"code": code, "msg": message, "data": None}


def business_error_handler(request, exc: BusinessError):
    return JSONResponse(status_code=exc.code, content=err(exc.message, exc.code))


def http_error_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=err(exc.detail, exc.status_code),
    )


def unhandled_handler(request, exc: Exception):
    return JSONResponse(status_code=500, content=err("服务器内部错误", 500))
