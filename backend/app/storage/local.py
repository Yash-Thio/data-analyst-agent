import json
import uuid
from pathlib import Path
from typing import Any

from app.config import settings


class LocalStorage:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.data_dir
        self.uploads_dir = self.base_dir / "uploads"
        self.artifacts_dir = self.base_dir / "artifacts"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def dataset_dir(self, dataset_id: str) -> Path:
        path = self.uploads_dir / dataset_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dataset_csv_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / "data.csv"

    def dataset_profile_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / "profile.json"

    def save_profile(self, dataset_id: str, profile: dict[str, Any]) -> None:
        path = self.dataset_profile_path(dataset_id)
        path.write_text(json.dumps(profile, indent=2, default=str))

    def load_profile(self, dataset_id: str) -> dict[str, Any] | None:
        path = self.dataset_profile_path(dataset_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def dataset_exists(self, dataset_id: str) -> bool:
        return self.dataset_csv_path(dataset_id).exists()

    def artifact_dir(self, session_id: str) -> Path:
        path = self.artifacts_dir / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_artifact(self, session_id: str, name: str, data: Any) -> Path:
        path = self.artifact_dir(session_id) / name
        if isinstance(data, (dict, list)):
            path.write_text(json.dumps(data, indent=2, default=str))
        else:
            path.write_text(str(data))
        return path

    def load_artifact(self, session_id: str, name: str) -> Any | None:
        path = self.artifact_dir(session_id) / name
        if not path.exists():
            return None
        if name.endswith(".json"):
            return json.loads(path.read_text())
        return path.read_text()


storage = LocalStorage()
