from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _positive_float(name: str, default: str) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_int(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    comfy_url: str
    state_dir: Path
    spool_dir: Path
    database_path: Path
    workflow_config_path: Path
    public_base_url: str
    comfy_poll_seconds: float
    comfy_timeout_seconds: float
    input_timeout_seconds: float
    input_max_bytes: int
    spool_retention_days: int
    admin_token: str

    @classmethod
    def from_env(cls) -> "Settings":
        state_dir = Path(os.getenv("STATE_DIR", "/data"))
        spool_dir = Path(os.getenv("SPOOL_DIR", str(state_dir / "spool")))
        return cls(
            comfy_url=os.getenv("COMFY_URL", "http://host.docker.internal:8188").rstrip("/"),
            state_dir=state_dir,
            spool_dir=spool_dir,
            database_path=Path(os.getenv("DATABASE_PATH", str(state_dir / "gateway.sqlite3"))),
            workflow_config_path=Path(
                os.getenv("WORKFLOW_CONFIG_PATH", "/app/config/workflow_config.json")
            ),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://gateway:8787").rstrip("/"),
            comfy_poll_seconds=_positive_float("COMFY_POLL_SECONDS", "1"),
            comfy_timeout_seconds=_positive_float("COMFY_TIMEOUT_SECONDS", "7200"),
            input_timeout_seconds=_positive_float("INPUT_TIMEOUT_SECONDS", "30"),
            input_max_bytes=_positive_int("INPUT_MAX_BYTES", "33554432"),
            spool_retention_days=_positive_int("SPOOL_RETENTION_DAYS", "7"),
            admin_token=os.getenv("GATEWAY_ADMIN_TOKEN", ""),
        )

    def prepare_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class WorkflowConfig:
    workflow_id: str
    source: str
    unet_name: str
    unet_weight_dtype: str
    clip_name: str
    clip_type: str
    clip_device: str
    vae_name: str
    sampler_name: str
    reference_megapixels: float
    reference_resolution_steps: int
    save_node_id: str
    minimum_comfy_version: str
    required_node_types: tuple[str, ...]
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "WorkflowConfig":
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        if raw.get("schema_version") != 1:
            raise ValueError("workflow config schema_version must be 1")
        models = raw["models"]
        reference = raw["reference_preprocessing"]
        required = tuple(raw["required_node_types"])
        if not required:
            raise ValueError("required_node_types cannot be empty")

        config = cls(
            workflow_id=str(raw["workflow_id"]),
            source=str(raw["source"]),
            unet_name=str(models["unet_name"]),
            unet_weight_dtype=str(models.get("unet_weight_dtype", "default")),
            clip_name=str(models["clip_name"]),
            clip_type=str(models.get("clip_type", "flux2")),
            clip_device=str(models.get("clip_device", "default")),
            vae_name=str(models["vae_name"]),
            sampler_name=str(raw.get("sampler_name", "euler")),
            reference_megapixels=float(reference.get("megapixels", 1.0)),
            reference_resolution_steps=int(reference.get("resolution_steps", 1)),
            save_node_id=str(raw.get("save_node_id", "13")),
            minimum_comfy_version=str(raw.get("minimum_comfy_version", "0.28.0")),
            required_node_types=required,
            raw=raw,
        )
        if config.reference_megapixels <= 0 or config.reference_resolution_steps <= 0:
            raise ValueError("reference preprocessing values must be positive")
        return config
