from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl

Status = Literal[
    "available",
    "absent",
    "not_exposed",
    "not_applicable",
    "skipped_by_policy",
    "failed",
    "no_speech_detected",
]
Mode = Literal["metadata", "auto", "evidence", "deep"]


class ExtractionRequest(BaseModel):
    url: HttpUrl
    mode: Mode = "auto"
    multimodal: bool = False
    force_refresh: bool = False


class ExtractionAccepted(BaseModel):
    id: str
    status: Literal["queued", "processing", "complete", "failed"]
    cached: bool = False


class FieldResult(BaseModel):
    status: Status
    value: Any = None
    source: str | None = None
    confidence: float | None = None


class ExtractionResult(BaseModel):
    id: str
    status: Literal["complete", "failed"]
    source: dict[str, Any]
    author: dict[str, Any] = Field(default_factory=dict)
    native: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    speech: dict[str, Any] = Field(default_factory=dict)
    media: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
