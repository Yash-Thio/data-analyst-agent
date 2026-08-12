from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.datasets import router as datasets_router
from app.api.sessions import router as sessions_router
from app.config import settings

app = FastAPI(title="Autonomous Data Analyst", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets_router)
app.include_router(sessions_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
