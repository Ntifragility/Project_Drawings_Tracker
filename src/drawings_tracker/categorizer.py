"""Drawing Document Categorizer.

Categorizes drawing IDs and file names into document category folders (CL, WD, LY, etc.)
using regex matching.
"""

from __future__ import annotations

import re
from pathlib import Path

# Mapping of 2-letter document codes to full descriptions
CATEGORY_MAP: dict[str, str] = {
    "CL": "Circuits List",
    "DC": "Design Criteria",
    "DS": "DataSheet",
    "EL": "Equipment List",
    "ER": "Equipment Requisition",
    "GL": "Grounding",
    "IF": "Informative",
    "LL": "Light",
    "LY": "Layout",
    "MC": "Memoria Calculo",
    "ML": "Materials List",
    "MR": "Material Requisition",
    "RD": "Reference Drawings",
    "SD": "Single Diagram",
    "SS": "Simbols",
    "TE": "Technical Evaluation",
    "TS": "Technical Specifications",
    "WD": "Wiring Diagram",
    "WR": "Weekly Report",
}

# Regex pattern matching 2-letter category code surrounded by hyphens before digits
# e.g., P22114-DA-3000-07-CL-001 -> CL
# Pattern matches -([A-Za-z]{2})-(?=\d)
CATEGORY_REGEX = re.compile(r"(?<=-)([A-Za-z]{2})(?=-\d+)")


def extract_category_code(*inputs: str) -> str | None:
    """Extract a 2-letter document category code from one or more input strings
    (e.g., drawing ID, file name).

    Returns uppercase 2-letter code if found in CATEGORY_MAP or matched by regex,
    otherwise returns None.
    """
    for text in inputs:
        if not text:
            continue
        match = CATEGORY_REGEX.search(text)
        if match:
            code = match.group(1).upper()
            if code in CATEGORY_MAP:
                return code

    # Fallback search for any known code in input text surrounded by non-alphanumerics
    for text in inputs:
        if not text:
            continue
        for code in CATEGORY_MAP:
            pattern = rf"(?i)(?<=[\-_]){re.escape(code)}(?=[\-_]|\b)"
            if re.search(pattern, text):
                return code

    return None


def get_category_folder(base_dir: str | Path, *identifiers: str) -> Path:
    """Determine the destination folder for a file based on its drawing ID or filename.

    Creates and returns `base_dir / CATEGORY` (e.g. `drawings/CL/`).
    If no category matches, returns `base_dir / OTHERS`.
    """
    base = Path(base_dir).resolve()
    code = extract_category_code(*identifiers)
    if code:
        target = base / code
    else:
        target = base / "OTHERS"

    target.mkdir(parents=True, exist_ok=True)
    return target
