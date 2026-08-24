from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .models import ComparisonResult, DrawingRecord


def load_excel_records(path: str | Path) -> list[DrawingRecord]:
    df = pd.read_excel(path)
    records: list[DrawingRecord] = []
    for _, row in df.iterrows():
        records.append(
            DrawingRecord(
                drawing_id=str(row.get("drawing_id") or row.get("Drawing ID") or row.get("drawing") or ""),
                project_code=row.get("project_code") or row.get("Project Code") or row.get("project"),
                revision=row.get("revision") or row.get("Revision") or row.get("rev"),
                status=row.get("status") or row.get("Status"),
                file_name=row.get("file_name") or row.get("File Name") or row.get("filename"),
                file_url=row.get("file_url") or row.get("File URL") or row.get("url"),
            )
        )
    return records


def compare_records(current: list[DrawingRecord], previous: list[DrawingRecord]) -> ComparisonResult:
    previous_map = {record.drawing_id: record for record in previous if record.drawing_id}

    new: list[DrawingRecord] = []
    updated: list[DrawingRecord] = []
    unchanged: list[DrawingRecord] = []

    for record in current:
        if not record.drawing_id:
            continue
        prev = previous_map.get(record.drawing_id)
        if prev is None:
            new.append(record)
        elif (prev.revision, prev.status, prev.file_url) != (record.revision, record.status, record.file_url):
            updated.append(record)
        else:
            unchanged.append(record)

    return ComparisonResult(new=new, updated=updated, unchanged=unchanged)
