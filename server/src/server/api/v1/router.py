from fastapi import APIRouter
from server.api.v1.routes.transcriptions import router as transcriptions_router
from server.api.v1.routes.uploads import router as uploads_router

api_router = APIRouter()
api_router.include_router(uploads_router, prefix="/uploads", tags=["uploads"])
api_router.include_router(transcriptions_router, prefix="/transcriptions", tags=["transcriptions"])