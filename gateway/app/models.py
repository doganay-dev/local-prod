from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ImageSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=512, le=2048)
    height: int = Field(ge=512, le=2048)

    @field_validator("width", "height")
    @classmethod
    def multiple_of_sixteen(cls, value: int) -> int:
        if value % 16:
            raise ValueError("must be a multiple of 16")
        return value


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=30000)
    image_urls: list[str] = Field(min_length=1, max_length=4)
    image_size: ImageSize
    # SQLite persists the seed as a signed INTEGER; Comfy accepts this full range.
    seed: int = Field(ge=0, le=9_223_372_036_854_775_807)
    negative_prompt: str = Field(default="", max_length=30000)
    guidance_scale: float = Field(default=5.0, gt=0, le=20)
    num_inference_steps: int = Field(default=28, ge=1, le=100)
    output_format: Literal["png"] = "png"
    sync_mode: bool = False
    num_images: Literal[1] = 1
    enable_prompt_expansion: Literal[False] = False

    @field_validator("image_urls")
    @classmethod
    def non_empty_references(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("image references cannot be empty")
        return values


class ImageResult(BaseModel):
    url: str
    width: int
    height: int
    content_type: Literal["image/png"] = "image/png"


class EditResponse(BaseModel):
    images: list[ImageResult]
    seed: int
    job_id: str
