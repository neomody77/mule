"""
Mule - Mobile Coding Assistant
服务入口
"""
import uvicorn
from app.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
