"""Tests for the drawing categorizer module."""

from pathlib import Path
from drawings_tracker.categorizer import (
    CATEGORY_MAP,
    extract_category_code,
    get_category_folder,
)


def test_extract_category_code_examples():
    assert extract_category_code("P22114-DA-3000-07-CL-001") == "CL"
    assert extract_category_code("P22-DA-3300-07-WD-036") == "WD"
    assert extract_category_code("P22METSO-DA-3300-07-LY-002") == "LY"


def test_extract_category_code_all_mapped_types():
    for code in CATEGORY_MAP.keys():
        sample = f"TEST-PREFIX-01-{code}-005"
        assert extract_category_code(sample) == code


def test_extract_category_code_unmatched():
    assert extract_category_code("RANDOM_FILE_NAME.pdf") is None
    assert extract_category_code("") is None


def test_get_category_folder(tmp_path: Path):
    base = Path(tmp_path).resolve()
    folder_cl = get_category_folder(base, "P22114-DA-3000-07-CL-001")
    assert folder_cl == base / "CL"
    assert folder_cl.exists()

    folder_others = get_category_folder(base, "UNMATCHED_NAME")
    assert folder_others == base / "OTHERS"
    assert folder_others.exists()
