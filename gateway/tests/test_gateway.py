from __future__ import annotations

import base64
from pathlib import Path

from conftest import PNG


EDIT_PATH = "/fal-ai/flux-2/klein/9b/base/edit"


def test_async_response_and_idempotent_reuse(app_client, edit_payload):
    client, _, fake = app_client

    first = client.post(EDIT_PATH, json=edit_payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["seed"] == 40040040
    assert len(body["job_id"]) == 64
    assert body["images"] == [
        {
            "url": f"http://gateway:8787/files/{body['job_id']}.png",
            "width": 1024,
            "height": 1024,
            "content_type": "image/png",
        }
    ]
    assert client.get(f"/files/{body['job_id']}.png").content == PNG

    second = client.post(EDIT_PATH, json=edit_payload)
    assert second.status_code == 200
    assert second.json() == body
    assert len(fake.graphs) == 1


def test_sync_mode_reuses_same_render_and_returns_data_uri(app_client, edit_payload):
    client, _, fake = app_client
    async_result = client.post(EDIT_PATH, json=edit_payload).json()
    edit_payload["sync_mode"] = True

    response = client.post(EDIT_PATH, json=edit_payload)
    assert response.status_code == 200
    assert response.json()["job_id"] == async_result["job_id"]
    url = response.json()["images"][0]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG
    assert len(fake.graphs) == 1


def test_graph_wires_all_references_in_order(app_client, edit_payload):
    client, _, fake = app_client
    edit_payload["image_urls"].append(edit_payload["image_urls"][0])
    edit_payload["image_size"] = {"width": 1248, "height": 832}

    response = client.post(EDIT_PATH, json=edit_payload)
    assert response.status_code == 200, response.text
    graph = fake.graphs[0]
    assert graph["8"]["inputs"] == {"steps": 28, "width": 1248, "height": 832}
    assert graph["9"]["inputs"] == {"width": 1248, "height": 832, "batch_size": 1}
    assert graph["10"]["inputs"]["cfg"] == 5
    assert graph["6"]["inputs"]["noise_seed"] == 40040040
    assert graph["100"]["inputs"]["image"] == "ref-1.png"
    assert graph["110"]["inputs"]["image"] == "ref-2.png"
    assert graph["10"]["inputs"]["positive"] == ["113", 0]
    assert graph["10"]["inputs"]["negative"] == ["114", 0]
    assert all(
        node["class_type"]
        in set(client.app.state.gateway.workflow_config.required_node_types)
        for node in graph.values()
    )


def test_reference_bytes_not_url_define_identity(app_client, edit_payload):
    client, _, fake = app_client
    first = client.post(EDIT_PATH, json=edit_payload).json()
    edit_payload["image_urls"] = [
        "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
    ]
    second = client.post(EDIT_PATH, json=edit_payload).json()
    assert first["job_id"] == second["job_id"]
    assert len(fake.graphs) == 1


def test_validation_errors_do_not_trip_circuit(app_client, edit_payload):
    client, _, _ = app_client
    edit_payload["image_size"]["width"] = 1000
    response = client.post(EDIT_PATH, json=edit_payload)
    assert response.status_code == 422
    assert client.app.state.gateway.store.circuit().is_open is False

    edit_payload["image_size"]["width"] = 1024
    edit_payload["image_urls"] = ["ftp://not-allowed/image.png"]
    response = client.post(EDIT_PATH, json=edit_payload)
    assert response.status_code == 400
    assert client.app.state.gateway.store.circuit().is_open is False


def test_comfy_failure_opens_circuit_and_requires_explicit_job_reset(app_client, edit_payload):
    client, _, fake = app_client
    fake.fail_prompt = True
    failed = client.post(EDIT_PATH, json=edit_payload)
    assert failed.status_code == 502
    job_id = client.app.state.gateway.store.get_job(
        next(iter(_job_ids(client.app.state.gateway.settings.database_path)))
    ).id
    assert client.app.state.gateway.store.circuit().is_open is True
    assert client.post(EDIT_PATH, json=edit_payload).status_code == 409

    headers = {"X-Gateway-Admin-Token": "test-secret"}
    assert client.post(f"/admin/jobs/{job_id}/reset", headers=headers).status_code == 204
    assert client.post("/admin/circuit/reset", headers=headers).status_code == 204
    fake.fail_prompt = False
    retried = client.post(EDIT_PATH, json=edit_payload)
    assert retried.status_code == 200, retried.text
    assert retried.json()["job_id"] == job_id


def _job_ids(database_path: Path):
    import sqlite3

    with sqlite3.connect(database_path) as connection:
        return [row[0] for row in connection.execute("SELECT id FROM jobs")]


def test_health_requires_comfy_nodes_models_version_and_closed_circuit(app_client):
    client, _, _ = app_client
    response = client.get("/healthz")
    assert response.status_code == 200, response.text
    assert response.json()["healthy"] is True
    assert response.json()["comfy_version"] == "0.28.0"


def test_file_path_is_not_user_controlled(app_client):
    client, _, _ = app_client
    assert client.get("/files/not-a-job.png").status_code == 404

