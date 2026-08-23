"""Output schema for the extraction task under test.

`evidence` is the load-bearing field: the spec requires a verbatim span from the
source document. Whether models actually honor that is the question the spike
exists to answer -- see `graders/set_grader.py::evidence_is_verbatim`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Competitor(BaseModel):
    name: str = Field(description="Company as named in the document")
    evidence: str = Field(description="Verbatim span (<=25 words) supporting inclusion")
    confidence: Confidence


class Extraction(BaseModel):
    competitors: list[Competitor] = Field(default_factory=list)
    summary: str = Field(description="2-3 sentences on the competitive landscape")


# JSON Schema handed to the API via output_config.format for the `structured` config.
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["name", "evidence", "confidence"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["competitors", "summary"],
    "additionalProperties": False,
}


class Case(BaseModel):
    """A labeled evaluation case."""

    case_id: str
    bucket: str
    source_path: str
    expected_competitors: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    notes: str = ""
