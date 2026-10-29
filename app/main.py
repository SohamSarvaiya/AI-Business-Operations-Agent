from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import router
from app.db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Business Operations Agent", version="1.0.0", lifespan=lifespan,
              description="Read-only agent: understands a business request, calls tools, returns a structured report with data sources.")
app.include_router(router)


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
