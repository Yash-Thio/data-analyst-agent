from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.data.profiler import profile_dataset
from app.storage.local import storage

router = APIRouter(prefix="/datasets", tags=["datasets"])

CHUNK_SIZE = 1024 * 1024


def _save_within_limit(file: UploadFile, csv_path: Path, max_bytes: int) -> None:
    """Stream the upload to disk, aborting once it exceeds max_bytes.

    Every analysis step reloads the whole CSV into an in-memory DuckDB, so an
    unbounded upload exhausts the container's memory rather than its disk.
    """
    written = 0
    with csv_path.open("wb") as f:
        while chunk := file.file.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                break
            f.write(chunk)

    if written > max_bytes:
        csv_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=(
                f"CSV is larger than the {settings.max_upload_mb} MB limit. "
                "Upload a smaller file or a sample of the data."
            ),
        )


class DatasetResponse(BaseModel):
    dataset_id: str
    profile: dict[str, Any]


@router.post("", response_model=DatasetResponse)
async def upload_dataset(file: UploadFile = File(...)) -> DatasetResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    dataset_id = storage.new_id()
    csv_path = storage.dataset_csv_path(dataset_id)

    _save_within_limit(file, csv_path, settings.max_upload_mb * 1024 * 1024)

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
