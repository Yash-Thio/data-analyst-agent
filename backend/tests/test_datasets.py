"""Dataset upload guards."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.storage.local import storage


@pytest.fixture
def client():
    return TestClient(app)


def test_non_csv_is_rejected(client) -> None:
    response = client.post(
        "/datasets", files={"file": ("notes.txt", b"a,b\n1,2\n", "text/plain")}
    )
    assert response.status_code == 400


def test_oversized_csv_is_rejected_and_leaves_nothing_behind(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    oversized = io.BytesIO(b"col\n" + b"x\n" * (2 * 1024 * 1024))

    before = set(settings.uploads_dir.iterdir())
    response = client.post(
        "/datasets", files={"file": ("big.csv", oversized, "text/csv")}
    )

    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    # The partial write is cleaned up, so a rejected upload costs no disk.
    new_dirs = set(settings.uploads_dir.iterdir()) - before
    assert all(not storage.dataset_exists(d.name) for d in new_dirs)


def test_upload_within_the_limit_succeeds(client, sales_csv) -> None:
    with sales_csv.open("rb") as f:
        response = client.post(
            "/datasets", files={"file": ("sales.csv", f, "text/csv")}
        )
    assert response.status_code == 200
    assert response.json()["profile"]["row_count"] > 0
