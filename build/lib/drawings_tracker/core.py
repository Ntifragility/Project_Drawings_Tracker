from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class DrawingTracker:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "tracker_state.json"
        self.history_path = self.data_dir / "history.csv"

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        with self.state_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save_state(self, state: dict[str, Any]) -> None:
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)

    def _load_history(self) -> pd.DataFrame:
        if not self.history_path.exists():
            return pd.DataFrame(columns=["drawing_id", "revision", "status", "project_code", "source_file", "timestamp"])
        return pd.read_csv(self.history_path)

    def _save_history(self, history: pd.DataFrame) -> None:
        history.to_csv(self.history_path, index=False)

    def _find_column(self, frame: pd.DataFrame, *candidates: str) -> str | None:
        normalized = {str(column).strip().lower().replace(" ", "_"): column for column in frame.columns}
        for candidate in candidates:
            if candidate in normalized:
                return normalized[candidate]
        return None

    def compare_status_files(self, previous_file: str | Path, latest_file: str | Path) -> dict[str, Any]:
        previous_df = pd.read_excel(previous_file)
        latest_df = pd.read_excel(latest_file)

        previous_df = previous_df.fillna("")
        latest_df = latest_df.fillna("")

        previous_df = previous_df.copy()
        latest_df = latest_df.copy()

        drawing_column = self._find_column(latest_df, "drawing_id", "drawing", "drawing_no", "drawingnumber")
        project_column = self._find_column(latest_df, "project_code", "project", "projectcode")
        revision_column = self._find_column(latest_df, "revision", "rev")
        status_column = self._find_column(latest_df, "status", "state")

        if drawing_column is None:
            raise ValueError("The Excel file must contain a drawing identifier column such as 'drawing_id'.")

        previous_df["drawing_id"] = previous_df[drawing_column].astype(str).str.strip()
        latest_df["drawing_id"] = latest_df[drawing_column].astype(str).str.strip()

        previous_df["project_code"] = previous_df[project_column] if project_column else ""
        latest_df["project_code"] = latest_df[project_column] if project_column else ""

        previous_df["revision"] = previous_df[revision_column] if revision_column else ""
        latest_df["revision"] = latest_df[revision_column] if revision_column else ""

        previous_df["status"] = previous_df[status_column] if status_column else ""
        latest_df["status"] = latest_df[status_column] if status_column else ""

        previous_index = previous_df.set_index("drawing_id")
        latest_index = latest_df.set_index("drawing_id")

        new_drawings: list[dict[str, Any]] = []
        updated_drawings: list[dict[str, Any]] = []

        for drawing_id in latest_index.index:
            latest_row = latest_index.loc[drawing_id]
            if drawing_id not in previous_index.index:
                new_drawings.append({
                    "drawing_id": drawing_id,
                    "revision": str(latest_row["revision"]),
                    "status": str(latest_row["status"]),
                    "project_code": str(latest_row.get("project_code", "")),
                })
                continue

            previous_row = previous_index.loc[drawing_id]
            prev_revision = str(previous_row["revision"])
            latest_revision = str(latest_row["revision"])
            prev_status = str(previous_row["status"])
            latest_status = str(latest_row["status"])

            if prev_revision != latest_revision or prev_status != latest_status:
                updated_drawings.append({
                    "drawing_id": drawing_id,
                    "previous_revision": prev_revision,
                    "latest_revision": latest_revision,
                    "previous_status": prev_status,
                    "latest_status": latest_status,
                    "project_code": str(latest_row.get("project_code", "")),
                })

        state = self._load_state()
        state["last_comparison"] = {
            "previous_file": str(previous_file),
            "latest_file": str(latest_file),
            "new_drawings": len(new_drawings),
            "updated_drawings": len(updated_drawings),
        }
        self._save_state(state)

        return {
            "new_drawings": new_drawings,
            "updated_drawings": updated_drawings,
        }

    def record_downloads(self, changes: dict[str, Any], download_root: str | Path) -> None:
        history = self._load_history()
        download_root = Path(download_root)
        download_root.mkdir(parents=True, exist_ok=True)

        for change in changes.get("new_drawings", []) + changes.get("updated_drawings", []):
            drawing_id = change["drawing_id"]
            revision = change.get("revision", change.get("latest_revision", ""))
            status = change.get("status", change.get("latest_status", ""))
            project_code = str(change.get("project_code", "unknown")).strip() or "unknown"
            safe_name = f"{drawing_id}_{revision}" if revision else drawing_id
            target_dir = download_root / project_code.replace("/", "_")
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / f"{safe_name}.txt"
            destination.write_text(
                f"drawing_id={drawing_id}\nrevision={revision}\nstatus={status}\n",
                encoding="utf-8",
            )
            history = pd.concat([
                history,
                pd.DataFrame([{
                    "drawing_id": drawing_id,
                    "revision": revision,
                    "status": status,
                    "project_code": project_code,
                    "source_file": str(destination),
                    "timestamp": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                }]),
            ], ignore_index=True)

        self._save_history(history)
