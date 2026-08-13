from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse

import httpx

from .comfy import ComfyClient, ComfyError
from .config import Settings, WorkflowConfig
from .models import EditRequest, EditResponse, ImageResult
from .store import Job, Store
from .workflow import KleinWorkflowBuilder


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DATA_URI = re.compile(r"^data:([^;,]+)(;base64)?,(.*)$", re.DOTALL | re.IGNORECASE)
MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class InputReferenceError(RuntimeError):
    pass


class CircuitOpenError(RuntimeError):
    pass


class StoredJobError(RuntimeError):
    pass


class ExpiredJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedImage:
    content: bytes
    mime_type: str
    sha256: str


class InputResolver:
    def __init__(
        self,
        max_bytes: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.max_bytes = max_bytes
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10)),
            transport=transport,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def resolve_all(self, references: list[str]) -> list[ResolvedImage]:
        # Preserve caller order; it is semantically meaningful for multi-reference edits.
        return [await self.resolve(reference) for reference in references]

    async def resolve(self, reference: str) -> ResolvedImage:
        if reference.lower().startswith("data:"):
            return self._data_uri(reference)
        parsed = urlparse(reference)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InputReferenceError("image references must be data:, http:, or https: URLs")
        try:
            async with self.client.stream("GET", reference) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and int(length) > self.max_bytes:
                    raise InputReferenceError("image reference exceeds INPUT_MAX_BYTES")
                mime_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise InputReferenceError("image reference exceeds INPUT_MAX_BYTES")
                    chunks.append(chunk)
        except InputReferenceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise InputReferenceError(f"could not fetch image reference: {exc}") from exc
        content = b"".join(chunks)
        return self._resolved(content, mime_type)

    def _data_uri(self, reference: str) -> ResolvedImage:
        match = DATA_URI.match(reference)
        if not match:
            raise InputReferenceError("invalid data URI")
        mime_type, encoded, payload = match.groups()
        mime_type = mime_type.lower()
        # Reject before decoding when a base64 payload is obviously over the byte limit.
        if encoded and len(payload) > ((self.max_bytes + 2) // 3) * 4 + 4:
            raise InputReferenceError("image reference exceeds INPUT_MAX_BYTES")
        try:
            content = base64.b64decode(payload, validate=True) if encoded else unquote_to_bytes(payload)
        except (binascii.Error, ValueError) as exc:
            raise InputReferenceError("invalid data URI payload") from exc
        if len(content) > self.max_bytes:
            raise InputReferenceError("image reference exceeds INPUT_MAX_BYTES")
        return self._resolved(content, mime_type)

    @staticmethod
    def _resolved(content: bytes, mime_type: str) -> ResolvedImage:
        detected = InputResolver._detected_mime(content)
        if not detected:
            raise InputReferenceError("image reference did not contain PNG, JPEG, or WebP bytes")
        if mime_type not in MIME_EXTENSIONS:
            mime_type = detected
        elif mime_type != detected:
            raise InputReferenceError(
                f"image content type {mime_type!r} did not match its {detected!r} bytes"
            )
        if mime_type not in MIME_EXTENSIONS:
            raise InputReferenceError(
                f"unsupported image content type {mime_type!r}; expected PNG, JPEG, or WebP"
            )
        if not content:
            raise InputReferenceError("image reference is empty")
        return ResolvedImage(content, mime_type, hashlib.sha256(content).hexdigest())

    @staticmethod
    def _detected_mime(content: bytes) -> str | None:
        if content.startswith(PNG_SIGNATURE):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        return None


class GatewayService:
    def __init__(
        self,
        settings: Settings,
        workflow_config: WorkflowConfig,
        store: Store,
        comfy: ComfyClient,
        input_resolver: InputResolver,
    ):
        self.settings = settings
        self.workflow_config = workflow_config
        self.store = store
        self.comfy = comfy
        self.input_resolver = input_resolver
        self.builder = KleinWorkflowBuilder(workflow_config)
        self.gpu_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.input_resolver.close()
        await self.comfy.close()

    async def edit(self, request: EditRequest) -> EditResponse:
        references = await self.input_resolver.resolve_all(request.image_urls)
        job_id, request_json = self._identity(request, references)

        existing = self.store.get_job(job_id)
        if existing and existing.state == "succeeded":
            return self._response(existing, request.sync_mode)
        if existing and existing.state == "failed":
            raise StoredJobError(existing.error or "this deterministic job previously failed")

        circuit = self.store.circuit()
        if circuit.is_open:
            raise CircuitOpenError(circuit.reason or "gateway circuit breaker is open")

        self.store.create_job(job_id, request_json, request.seed)
        async with self.gpu_lock:
            job = self.store.get_job(job_id)
            assert job is not None
            if job.state == "succeeded":
                return self._response(job, request.sync_mode)
            if job.state == "failed":
                raise StoredJobError(job.error or "this deterministic job previously failed")
            circuit = self.store.circuit()
            if circuit.is_open:
                raise CircuitOpenError(circuit.reason or "gateway circuit breaker is open")

            try:
                output_path = await self._execute(job, request, references)
                self.store.mark_succeeded(
                    job_id,
                    output_path,
                    request.image_size.width,
                    request.image_size.height,
                )
            except ComfyError as exc:
                message = f"job {job_id}: {exc}"
                self.store.mark_failed(job_id, message)
                self.store.open_circuit(message)
                raise ComfyError(message) from exc

        completed = self.store.get_job(job_id)
        assert completed is not None
        return self._response(completed, request.sync_mode)

    async def _execute(
        self,
        job: Job,
        request: EditRequest,
        references: list[ResolvedImage],
    ) -> Path:
        prompt_id = job.prompt_id
        if job.state == "running" and not prompt_id:
            prompt_id = await self.comfy.find_prompt_by_job_id(job.id)
            if not prompt_id:
                raise ComfyError(
                    "gateway restarted during an ambiguous Comfy submission; refusing automatic rerender"
                )
            self.store.set_prompt_id(job.id, prompt_id)

        if not prompt_id:
            uploaded: list[str] = []
            for index, reference in enumerate(references, start=1):
                extension = MIME_EXTENSIONS[reference.mime_type]
                filename = f"gateway_{job.id}_{index}{extension}"
                uploaded.append(
                    await self.comfy.upload_image(filename, reference.content, reference.mime_type)
                )
            graph = self.builder.build(request, uploaded, job.id)
            # 'running without prompt_id' deliberately means an ambiguous POST after a crash.
            self.store.mark_running(job.id)
            prompt_id = await self.comfy.queue_prompt(graph, job.id)
            self.store.set_prompt_id(job.id, prompt_id)

        output = await self.comfy.wait_for_output(prompt_id, self.workflow_config.save_node_id)
        content = await self.comfy.download_output(output)
        if not content.startswith(PNG_SIGNATURE):
            raise ComfyError("Comfy output was not a PNG")
        output_path = self.settings.spool_dir / f"{job.id}.png"
        temporary = self.settings.spool_dir / f".{job.id}.{os.getpid()}.tmp"
        temporary.write_bytes(content)
        temporary.replace(output_path)
        return output_path

    def _identity(
        self, request: EditRequest, references: list[ResolvedImage]
    ) -> tuple[str, str]:
        identity: dict[str, Any] = {
            "workflow_hash": self.builder.workflow_hash,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "width": request.image_size.width,
            "height": request.image_size.height,
            "seed": request.seed,
            "guidance_scale": request.guidance_scale,
            "num_inference_steps": request.num_inference_steps,
            "output_format": request.output_format,
            "reference_sha256": [reference.sha256 for reference in references],
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded

    def _response(self, job: Job, sync_mode: bool) -> EditResponse:
        if job.state != "succeeded" or not job.width or not job.height:
            raise RuntimeError(f"job {job.id} is not complete")
        if not job.output_path:
            raise ExpiredJobError(f"job {job.id} output passed its retention period")
        path = Path(job.output_path)
        if not path.is_file():
            raise ExpiredJobError(f"job {job.id} output is no longer available")
        if sync_mode:
            url = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            url = f"{self.settings.public_base_url}/files/{job.id}.png"
        return EditResponse(
            images=[ImageResult(url=url, width=job.width, height=job.height)],
            seed=job.seed,
            job_id=job.id,
        )

    def file_for_job(self, job_id: str) -> Path:
        job = self.store.get_job(job_id)
        if not job or job.state != "succeeded" or not job.output_path:
            raise ExpiredJobError("output was not found")
        path = Path(job.output_path)
        try:
            path.resolve().relative_to(self.settings.spool_dir.resolve())
        except ValueError as exc:
            raise ExpiredJobError("stored output path was invalid") from exc
        if not path.is_file():
            raise ExpiredJobError("output was not found")
        return path

    def prune_expired_outputs(self) -> int:
        cutoff = time.time() - self.settings.spool_retention_days * 86400
        removed = 0
        for job in self.store.expired_outputs(cutoff):
            if not job or not job.output_path:
                continue
            path = Path(job.output_path)
            try:
                path.resolve().relative_to(self.settings.spool_dir.resolve())
            except ValueError:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            self.store.expire_output(job.id)
            removed += 1
        return removed

    async def health(self) -> dict[str, Any]:
        stats, objects = await self.comfy.health()
        missing_nodes = sorted(set(self.workflow_config.required_node_types) - set(objects))
        missing_models = self._missing_models(objects)
        version = str(stats.get("system", {}).get("comfyui_version", ""))
        version_ok = bool(version) and self._version_tuple(version) >= self._version_tuple(
            self.workflow_config.minimum_comfy_version
        )
        circuit = self.store.circuit()
        healthy = not missing_nodes and not missing_models and version_ok and not circuit.is_open
        return {
            "healthy": healthy,
            "comfy_reachable": True,
            "comfy_version": version or None,
            "minimum_comfy_version": self.workflow_config.minimum_comfy_version,
            "workflow_id": self.workflow_config.workflow_id,
            "workflow_hash": self.builder.workflow_hash,
            "missing_node_types": missing_nodes,
            "missing_models": missing_models,
            "circuit": {
                "open": circuit.is_open,
                "reason": circuit.reason,
                "updated_at": circuit.updated_at,
            },
            "jobs": self.store.job_counts(),
        }

    def _missing_models(self, objects: dict[str, Any]) -> list[str]:
        checks = (
            ("UNETLoader", "unet_name", self.workflow_config.unet_name),
            ("CLIPLoader", "clip_name", self.workflow_config.clip_name),
            ("VAELoader", "vae_name", self.workflow_config.vae_name),
        )
        missing: list[str] = []
        for node, field, expected in checks:
            try:
                choices = objects[node]["input"]["required"][field][0]
            except (KeyError, IndexError, TypeError):
                missing.append(f"{node}:{expected} (could not inspect choices)")
                continue
            if expected not in choices:
                missing.append(f"{node}:{expected}")
        return missing

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", value)
        return tuple(int(number) for number in numbers[:3])
