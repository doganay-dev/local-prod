from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .config import WorkflowConfig
from .models import EditRequest


class WorkflowError(RuntimeError):
    pass


class KleinWorkflowBuilder:
    """Build the allowlisted API graph matching Comfy's official Klein 9B edit graph."""

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.workflow_hash = hashlib.sha256(
            json.dumps(config.raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self._allowed = set(config.required_node_types)

    def build(
        self,
        request: EditRequest,
        uploaded_images: list[str],
        job_id: str,
    ) -> dict[str, dict[str, Any]]:
        if not 1 <= len(uploaded_images) <= 4:
            raise WorkflowError("the canonical graph supports one to four references")

        graph: dict[str, dict[str, Any]] = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": self.config.unet_name,
                    "weight_dtype": self.config.unet_weight_dtype,
                },
            },
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": self.config.clip_name,
                    "type": self.config.clip_type,
                    "device": self.config.clip_device,
                },
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": self.config.vae_name},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": request.prompt},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": request.negative_prompt},
            },
            "6": {
                "class_type": "RandomNoise",
                "inputs": {"noise_seed": request.seed},
            },
            "7": {
                "class_type": "KSamplerSelect",
                "inputs": {"sampler_name": self.config.sampler_name},
            },
            "8": {
                "class_type": "Flux2Scheduler",
                "inputs": {
                    "steps": request.num_inference_steps,
                    "width": request.image_size.width,
                    "height": request.image_size.height,
                },
            },
            "9": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {
                    "width": request.image_size.width,
                    "height": request.image_size.height,
                    "batch_size": 1,
                },
            },
            "10": {
                "class_type": "CFGGuider",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "cfg": request.guidance_scale,
                },
            },
            "11": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["6", 0],
                    "guider": ["10", 0],
                    "sampler": ["7", 0],
                    "sigmas": ["8", 0],
                    "latent_image": ["9", 0],
                },
            },
            "12": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
            },
            self.config.save_node_id: {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["12", 0],
                    "filename_prefix": f"gateway/{job_id}",
                },
            },
        }

        positive: list[Any] = ["4", 0]
        negative: list[Any] = ["5", 0]
        for index, image_name in enumerate(uploaded_images):
            base = 100 + index * 10
            load_id = str(base)
            scale_id = str(base + 1)
            encode_id = str(base + 2)
            positive_id = str(base + 3)
            negative_id = str(base + 4)
            graph.update(
                {
                    load_id: {
                        "class_type": "LoadImage",
                        "inputs": {"image": image_name},
                    },
                    scale_id: {
                        "class_type": "ImageScaleToTotalPixels",
                        "inputs": {
                            "image": [load_id, 0],
                            "upscale_method": "lanczos",
                            "megapixels": self.config.reference_megapixels,
                            "resolution_steps": self.config.reference_resolution_steps,
                        },
                    },
                    encode_id: {
                        "class_type": "VAEEncode",
                        "inputs": {"pixels": [scale_id, 0], "vae": ["3", 0]},
                    },
                    positive_id: {
                        "class_type": "ReferenceLatent",
                        "inputs": {"conditioning": deepcopy(positive), "latent": [encode_id, 0]},
                    },
                    negative_id: {
                        "class_type": "ReferenceLatent",
                        "inputs": {"conditioning": deepcopy(negative), "latent": [encode_id, 0]},
                    },
                }
            )
            positive = [positive_id, 0]
            negative = [negative_id, 0]

        graph["10"]["inputs"]["positive"] = positive
        graph["10"]["inputs"]["negative"] = negative
        self._validate_allowlist(graph)
        return graph

    def _validate_allowlist(self, graph: dict[str, dict[str, Any]]) -> None:
        used = {node.get("class_type") for node in graph.values()}
        unexpected = used - self._allowed
        if unexpected:
            raise WorkflowError(f"graph contains non-allowlisted node types: {sorted(unexpected)}")

