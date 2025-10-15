from fastapi import FastAPI

from app.routers import command

app = FastAPI(title="XY Assistant API", version="0.1.0")

app.include_router(command.router)


@app.get("/health", summary="服务健康检查")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
