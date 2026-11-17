from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from app.shared.quota_policy import QuotaExceededError, QuotaResourceNotFoundError

class IAMException(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

def setup_exception_handlers(app: FastAPI):
    @app.exception_handler(QuotaResourceNotFoundError)
    async def quota_resource_missing_handler(request: Request, exc: QuotaResourceNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(QuotaExceededError)
    async def quota_exception_handler(request: Request, exc: QuotaExceededError):
        return JSONResponse(status_code=403, content={"detail": {
            "code": exc.code, "message": exc.message, "current": exc.current, "limit": exc.limit,
        }})

    @app.exception_handler(IAMException)
    async def iam_exception_handler(request: Request, exc: IAMException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message}
        )
    
    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Database integrity error"}
        )
