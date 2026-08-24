from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DrawingRecord:
    drawing_id: str
    project_code: str | None = None
    revision: str | None = None
    status: str | None = None
    file_name: str | None = None
    file_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawing_id": self.drawing_id,
            "project_code": self.project_code,
            "revision": self.revision,
            "status": self.status,
            "file_name": self.file_name,
            "file_url": self.file_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DrawingRecord":
        return cls(
            drawing_id=str(data.get("drawing_id", "")),
            project_code=data.get("project_code"),
            revision=data.get("revision"),
            status=data.get("status"),
            file_name=data.get("file_name"),
            file_url=data.get("file_url"),
        )


@dataclass(slots=True)
class ComparisonResult:
    new: list[DrawingRecord]
    updated: list[DrawingRecord]
    unchanged: list[DrawingRecord]

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "new": [item.to_dict() for item in self.new],
            "updated": [item.to_dict() for item in self.updated],
            "unchanged": [item.to_dict() for item in self.unchanged],
        }


def build_output_path(base_dir: str | Path, record: DrawingRecord) -> Path:
    base = Path(base_dir)
    project_code = (record.project_code or "unknown").strip().replace("/", "_")
    drawing_id = (record.drawing_id or "unknown").strip().replace("/", "_")
    revision = record.revision or "rev"
    return base / project_code / f"{drawing_id}_{revision}"
