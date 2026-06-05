from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routes import router
from common.db import close_pool, init_pool


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Мониторинг криптовалютного портфеля", lifespan=lifespan)
app.include_router(router)

_webapp_dir = Path(__file__).resolve().parents[2] / "webapp"
if _webapp_dir.exists():
    app.mount("/webapp", StaticFiles(directory=str(_webapp_dir), html=True), name="webapp")
    app.mount("/site", StaticFiles(directory=str(_webapp_dir), html=True), name="site")


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(_webapp_dir / "index.html")
