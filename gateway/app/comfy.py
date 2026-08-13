from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx


class ComfyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComfyOutput:
    filename: str
    subfolder: str
    type: str


class ComfyClient:
    def __init__(
        self,
        base_url: str,
        poll_seconds: float,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60, connect=10),
            transport=transport,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ComfyError(f"Comfy {method} {path} failed: {exc}") from exc

    async def upload_image(self, filename: str, content: bytes, mime_type: str) -> str:
        payload = await self._json(
            "POST",
            "/upload/image",
            files={"image": (filename, content, mime_type)},
            data={"overwrite": "true", "type": "input"},
        )
        try:
            name = str(payload["name"])
            subfolder = str(payload.get("subfolder", "")).strip("/")
        except (KeyError, TypeError) as exc:
            raise ComfyError("Comfy upload response did not contain an image name") from exc
        return f"{subfolder}/{name}" if subfolder else name

    async def queue_prompt(self, graph: dict[str, Any], job_id: str) -> str:
        payload = await self._json(
            "POST",
            "/prompt",
            json={
                "prompt": graph,
                "client_id": f"local-gateway-{job_id}",
                "extra_data": {"gateway_job_id": job_id},
            },
        )
        if payload.get("node_errors"):
            raise ComfyError(f"Comfy rejected graph: {payload['node_errors']}")
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ComfyError("Comfy prompt response did not contain prompt_id")
        return str(prompt_id)

    async def find_prompt_by_job_id(self, job_id: str) -> str | None:
        """Recover a prompt across a gateway restart without submitting it twice."""
        queue = await self._json("GET", "/queue")
        for section in ("queue_running", "queue_pending"):
            for item in queue.get(section, []):
                if self._prompt_item_job_id(item) == job_id and len(item) > 1:
                    return str(item[1])

        history = await self._json("GET", "/history", params={"max_items": 100})
        for prompt_id, record in history.items():
            if self._prompt_item_job_id(record.get("prompt", [])) == job_id:
                return str(prompt_id)
        return None

    @staticmethod
    def _prompt_item_job_id(item: Any) -> str | None:
        if not isinstance(item, (list, tuple)) or len(item) < 4 or not isinstance(item[3], dict):
            return None
        extra = item[3]
        return extra.get("gateway_job_id") or extra.get("extra_data", {}).get("gateway_job_id")

    async def wait_for_output(self, prompt_id: str, save_node_id: str) -> ComfyOutput:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = await self.client.get(f"/history/{prompt_id}")
                if response.status_code == 404:
                    history: dict[str, Any] = {}
                else:
                    response.raise_for_status()
                    history = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ComfyError(f"Comfy history poll failed: {exc}") from exc

            record = history.get(prompt_id)
            if record:
                output = self._find_output(record.get("outputs", {}), save_node_id)
                if output:
                    return output
                status = record.get("status", {})
                if status.get("completed"):
                    messages = status.get("messages", [])
                    raise ComfyError(
                        f"Comfy prompt ended without an image "
                        f"(status={status.get('status_str')!r}, messages={messages!r})"
                    )
            await asyncio.sleep(self.poll_seconds)
        raise ComfyError(f"Comfy prompt {prompt_id} exceeded {self.timeout_seconds:g}s")

    @staticmethod
    def _find_output(outputs: dict[str, Any], save_node_id: str) -> ComfyOutput | None:
        candidates: list[dict[str, Any]] = []
        if save_node_id in outputs:
            candidates.append(outputs[save_node_id])
        candidates.extend(value for key, value in outputs.items() if key != save_node_id)
        for candidate in candidates:
            images = candidate.get("images", []) if isinstance(candidate, dict) else []
            if images:
                image = images[0]
                return ComfyOutput(
                    filename=str(image["filename"]),
                    subfolder=str(image.get("subfolder", "")),
                    type=str(image.get("type", "output")),
                )
        return None

    async def download_output(self, output: ComfyOutput) -> bytes:
        try:
            response = await self.client.get(
                "/view",
                params={
                    "filename": output.filename,
                    "subfolder": output.subfolder,
                    "type": output.type,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyError(f"Comfy output download failed: {exc}") from exc
        if not response.content:
            raise ComfyError("Comfy returned an empty output image")
        return response.content

    async def health(self) -> tuple[dict[str, Any], dict[str, Any]]:
        stats = await self._json("GET", "/system_stats")
        objects = await self._json("GET", "/object_info")
        if not isinstance(stats, dict) or not isinstance(objects, dict):
            raise ComfyError("Comfy health responses were not JSON objects")
        return stats, objects
