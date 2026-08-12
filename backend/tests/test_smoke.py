"""Integration smoke tests that do not require an LLM API key."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

SAMPLE = Path(__file__).resolve().parents[2] / "sample-data" / "sales.csv"


def test_health():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"


def test_upload_and_session():
    client = TestClient(app)
    with SAMPLE.open("rb") as f:
        res = client.post("/datasets", files={"file": ("sales.csv", f, "text/csv")})
    assert res.status_code == 200
    data = res.json()
    assert data["profile"]["row_count"] == 16
    assert "revenue" in data["profile"]["numeric_columns"]

    session = client.post("/sessions", json={"dataset_id": data["dataset_id"]})
    assert session.status_code == 200
    assert "session_id" in session.json()


if __name__ == "__main__":
    test_health()
    test_upload_and_session()
    print("integration smoke OK")
