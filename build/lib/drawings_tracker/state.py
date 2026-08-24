from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._data: dict[str, Any] = {"downloaded": [], "last_checked": None}
            self.save()
        else:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def mark_downloaded(self, drawing_id: str, file_path: str) -> None:
        self._data.setdefault("downloaded", []).append({"drawing_id": drawing_id, "file_path": file_path})
        self.save()

    def set_last_checked(self, timestamp: str) -> None:
        self._data["last_checked"] = timestamp
        self.save()

    def get_downloaded_ids(self) -> set[str]:
        return {item["drawing_id"] for item in self._data.get("downloaded", []) if "drawing_id" in item}
