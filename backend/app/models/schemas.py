"""Pydantic request and response schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


class ExtractionRequest(BaseModel):
    """Request body for URL-based PDF extraction."""

    pdf_url: HttpUrl = Field(
        ...,
        description="Public URL of the NCERT PDF to extract.",
        examples=["https://ncert.nic.in/textbook/pdf/iesc101.pdf"],
    )
    document_type: Optional[str] = Field(default=None)
    document_title: Optional[str] = Field(default=None)
    chapter_number: Optional[str] = Field(default=None)
    standard: Optional[str] = Field(default=None)
    subject_name: Optional[str] = Field(default=None)
    board: Optional[str] = Field(default="CBSE")
    syear: Optional[str] = Field(default=None)


class HealthResponse(BaseModel):
    """Health-check response."""

    status: str = "ok"
    service: str = "ncert-pdf-extractor"
    version: str = "1.0.0"


class ExtractionResponse(BaseModel):
    """Successful extraction response."""

    status: str = "success"
    processing_mode: str = Field(
        default="cpu-mineru-pipeline",
        description="Extraction mode used for CPU document intelligence.",
    )
    markdown_content: str = Field(
        ...,
        description="Extracted content in Markdown format.",
    )
    json_content: Optional[dict[str, Any] | list[Any]] = Field(
        default=None,
        description="Structured JSON extraction data.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Processing timing, quality diagnostics, and extracted asset counts.",
    )
    page_count: Optional[int] = Field(
        default=None,
        description="Number of pages processed.",
    )
    images_extracted: int = Field(
        default=0,
        description="Number of images extracted.",
    )


class ErrorResponse(BaseModel):
    """Standard error response."""

    status: str = "error"
    message: str
    detail: Optional[str] = None
