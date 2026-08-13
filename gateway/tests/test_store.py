from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from app.store import Store


def test_prune_removes_only_expired_successful_outputs(app_client, edit_payload):
    client, app, _ = app_client
    result = client.post("/fal-ai/flux-2/klein/9b/base/edit", json=edit_payload).json()
    service = app.state.gateway
    job = service.store.get_job(result["job_id"])
    assert job and job.output_path
    with sqlite3.connect(service.settings.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (time.time() - 8 * 86400, result["job_id"]),
        )
    assert service.prune_expired_outputs() == 1
    assert not Path(job.output_path).exists()
    assert service.store.get_job(result["job_id"]).output_path is None


def test_reset_only_affects_failed_job(tmp_path: Path):
    store = Store(tmp_path / "jobs.sqlite3")
    store.create_job("a", "{}", 1)
    assert store.reset_failed_job("a") is False
    store.mark_failed("a", "failed")
    assert store.reset_failed_job("a") is True
    assert store.get_job("a").state == "queued"

