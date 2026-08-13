from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse

from .comfy import ComfyClient, ComfyError
from .config import Settings, WorkflowConfig
from .models import EditRequest, EditResponse
from .service import (
    CircuitOpenError,
    ExpiredJobError,
    GatewayService,
    InputReferenceError,
    InputResolver,
    StoredJobError,
)
from .store import Store


JOB_ID = re.compile(r"^[0-9a-f]{64}$")


def create_app(
    settings: Settings | None = None,
    comfy_transport: httpx.AsyncBaseTransport | None = None,
    input_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.prepare_directories()
    workflow_config = WorkflowConfig.load(settings.workflow_config_path)
    store = Store(settings.database_path)
    comfy = ComfyClient(
        settings.comfy_url,
        settings.comfy_poll_seconds,
        settings.comfy_timeout_seconds,
        transport=comfy_transport,
    )
    resolver = InputResolver(
        settings.input_max_bytes,
        settings.input_timeout_seconds,
        transport=input_transport,
    )
    service = GatewayService(settings, workflow_config, store, comfy, resolver)

    async def retention_loop() -> None:
        while True:
            service.prune_expired_outputs()
            await asyncio.sleep(86400)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        retention_task = asyncio.create_task(retention_loop())
        try:
            yield
        finally:
            retention_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retention_task
            await service.close()

    app = FastAPI(
        title="Local FLUX.2 Klein Gateway",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.gateway = service

    @app.post(
        "/fal-ai/flux-2/klein/9b/base/edit",
        response_model=EditResponse,
        response_model_exclude_none=True,
    )
    async def edit(request: EditRequest, response: Response) -> EditResponse:
        try:
            result = await service.edit(request)
        except InputReferenceError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except CircuitOpenError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        except StoredJobError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except ExpiredJobError as exc:
            raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
        except ComfyError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        response.headers["X-Gateway-Job-Id"] = result.job_id
        return result

    @app.get("/files/{job_id}.png", response_class=FileResponse)
    async def file(job_id: str) -> FileResponse:
        if not JOB_ID.fullmatch(job_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "output was not found")
        try:
            path = service.file_for_job(job_id)
        except ExpiredJobError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return FileResponse(path, media_type="image/png", filename=f"{job_id}.png")

    @app.get("/healthz")
    async def healthz(response: Response) -> dict:
        try:
            result = await service.health()
        except ComfyError as exc:
            result = {
                "healthy": False,
                "comfy_reachable": False,
                "error": str(exc),
                "circuit": service.store.circuit().__dict__,
                "jobs": service.store.job_counts(),
            }
        if not result["healthy"]:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return result

    @app.post("/admin/circuit/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset_circuit(x_gateway_admin_token: str = Header(default="")) -> Response:
        if not settings.admin_token:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "GATEWAY_ADMIN_TOKEN is not configured"
            )
        if not secrets.compare_digest(x_gateway_admin_token, settings.admin_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin token")
        store.reset_circuit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/admin/jobs/{job_id}/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset_failed_job(
        job_id: str, x_gateway_admin_token: str = Header(default="")
    ) -> Response:
        if not JOB_ID.fullmatch(job_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "failed job was not found")
        if not settings.admin_token:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "GATEWAY_ADMIN_TOKEN is not configured"
            )
        if not secrets.compare_digest(x_gateway_admin_token, settings.admin_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin token")
        if not store.reset_failed_job(job_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "failed job was not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app
