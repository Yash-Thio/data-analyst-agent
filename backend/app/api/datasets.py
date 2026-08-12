import json
import shutil
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.data.profiler import profile_dataset
from app.storage.local import storage

router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetResponse(BaseModel):
    dataset_id: str
    profile: dict[str, Any]


@router.post("", response_model=DatasetResponse)
async def upload_dataset(file: UploadFile = File(...)) -> DatasetResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    dataset_id = storage.new_id()
    csv_path = storage.dataset_csv_path(dataset_id)

    with csv_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        profile = profile_dataset(csv_path)
    except Exception as e:
        csv_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {e}") from e

    storage.save_profile(dataset_id, profile)
    return DatasetResponse(dataset_id=dataset_id, profile=profile)


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str) -> dict[str, Any]:
    if not storage.dataset_exists(dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    profile = storage.load_profile(dataset_id)
    return {"dataset_id": dataset_id, "profile": profile}
