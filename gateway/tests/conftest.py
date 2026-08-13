from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


PNG = b"\x89PNG\r\n\x1a\n" + b"test-png-data"


class FakeComfy:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.graphs: list[dict[str, Any]] = []
        self.prompt_ids: dict[str, str] = {}
        self.fail_prompt = False
        self.next_prompt = 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/upload/image" and request.method == "POST":
            index = sum(1 for _, called in self.calls if called == "/upload/image")
            return httpx.Response(200, json={"name": f"ref-{index}.png", "subfolder": ""})
        if path == "/prompt" and request.method == "POST":
            if self.fail_prompt:
                return httpx.Response(500, json={"error": "mock Comfy failure"})
            body = json.loads(request.content)
            self.graphs.append(body["prompt"])
            prompt_id = f"prompt-{self.next_prompt}"
            self.next_prompt += 1
            self.prompt_ids[prompt_id] = body["extra_data"]["gateway_job_id"]
            return httpx.Response(200, json={"prompt_id": prompt_id, "node_errors": {}})
        if path.startswith("/history/") and request.method == "GET":
            prompt_id = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    prompt_id: {
                        "outputs": {
                            "13": {
                                "images": [
                                    {"filename": "result.png", "subfolder": "gateway", "type": "output"}
                                ]
                            }
                        },
                        "status": {"completed": True, "status_str": "success"},
                    }
                },
            )
        if path == "/view" and request.method == "GET":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if path == "/system_stats" and request.method == "GET":
            return httpx.Response(200, json={"system": {"comfyui_version": "0.28.0"}})
        if path == "/object_info" and request.method == "GET":
            return httpx.Response(200, json=self.object_info())
        if path == "/queue" and request.method == "GET":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if path == "/history" and request.method == "GET":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"path": path})

    @staticmethod
    def object_info() -> dict[str, Any]:
        config = json.loads(
            (Path(__file__).parents[1] / "config" / "workflow_config.json").read_text("utf-8")
        )
        result = {name: {"input": {"required": {}}} for name in config["required_node_types"]}
        result["UNETLoader"]["input"]["required"]["unet_name"] = [
            [config["models"]["unet_name"]]
        ]
        result["CLIPLoader"]["input"]["required"]["clip_name"] = [
            [config["models"]["clip_name"]]
        ]
        result["VAELoader"]["input"]["required"]["vae_name"] = [
            [config["models"]["vae_name"]]
        ]
        return result


@pytest.fixture
def fake_comfy() -> FakeComfy:
    return FakeComfy()


@pytest.fixture
def app_client(tmp_path: Path, fake_comfy: FakeComfy):
    root = Path(__file__).parents[1]
    settings = Settings(
        comfy_url="http://mock-comfy",
        state_dir=tmp_path,
        spool_dir=tmp_path / "spool",
        database_path=tmp_path / "gateway.sqlite3",
        workflow_config_path=root / "config" / "workflow_config.json",
        public_base_url="http://gateway:8787",
        comfy_poll_seconds=0.001,
        comfy_timeout_seconds=1,
        input_timeout_seconds=1,
        input_max_bytes=1024 * 1024,
        spool_retention_days=7,
        admin_token="test-secret",
    )
    app = create_app(settings, comfy_transport=httpx.MockTransport(fake_comfy.handler))
    with TestClient(app) as client:
        yield client, app, fake_comfy


@pytest.fixture
def edit_payload() -> dict[str, Any]:
    import base64

    return {
        "prompt": "Keep geometry unchanged",
        "negative_prompt": "hardware",
        "image_urls": ["data:image/png;base64," + base64.b64encode(PNG).decode("ascii")],
        "image_size": {"width": 1024, "height": 1024},
        "seed": 40040040,
        "guidance_scale": 5,
        "num_inference_steps": 28,
        "output_format": "png",
        "sync_mode": False,
        "num_images": 1,
        "enable_prompt_expansion": False,
    }

