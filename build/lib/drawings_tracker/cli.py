from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DrawingTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare drawing status exports and track new or updated drawings")
    parser.add_argument("--current", required=True, help="Path to the latest Excel export")
    parser.add_argument("--previous", required=True, help="Path to the previous Excel export")
    parser.add_argument("--output-dir", default="downloads", help="Root folder where tracked drawing files will be stored")
    parser.add_argument("--data-dir", default="data", help="Directory for local tracker state and history")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current_path = Path(args.current)
    previous_path = Path(args.previous)

    tracker = DrawingTracker(data_dir=args.data_dir)
    changes = tracker.compare_status_files(previous_path, current_path)
    tracker.record_downloads(changes, args.output_dir)

    print(f"New drawings: {len(changes['new_drawings'])}")
    print(f"Updated drawings: {len(changes['updated_drawings'])}")

    for item in changes["new_drawings"]:
        print(f"NEW {item['drawing_id']} rev={item.get('revision', '')} project={item.get('project_code', '')}")
    for item in changes["updated_drawings"]:
        print(
            f"UPDATED {item['drawing_id']} {item.get('previous_revision', '')} -> {item.get('latest_revision', '')}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
