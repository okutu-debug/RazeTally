"""Shared PDF processing pipeline: rasterize → Claude Vision → DB."""

import os
import shutil
from pathlib import Path

from db import is_already_processed, save_to_db
from form_types import FORM_TYPE_MAP, detect_form_type
from parser import parse_form_vision
from rasterizer import load_pages

FORMS_DIR = Path("docs/forms")


def save_upload(file_bytes: bytes, filename: str) -> Path:
    """Save uploaded bytes to FORMS_DIR and return the path."""
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    dest = FORMS_DIR / filename
    dest.write_bytes(file_bytes)
    return dest


def process_pdf(pdf_path: Path, api_key: str, dpi: int = 300, force: bool = False) -> dict:
    """
    Full pipeline for one PDF: rasterize → Claude Vision → DB.
    Returns the structured result dict with an added 'form_type' key.
    Raises ValueError for bad filenames or duplicates; RuntimeError on pipeline failures.
    """
    form_type = detect_form_type(pdf_path)
    if form_type is None:
        raise ValueError(
            f"Unrecognised form type for '{pdf_path.name}'. "
            "Filename must start with F34A, F35A, F36A, F37A, F38A, or F39A."
        )

    source_key = str(pdf_path.resolve())

    if not force and is_already_processed(source_key, form_type):
        raise ValueError(f"'{pdf_path.name}' is already in the database.")

    try:
        page_images = load_pages(str(pdf_path), dpi=dpi)
    except Exception as exc:
        raise RuntimeError(f"Failed to rasterize '{pdf_path.name}': {exc}") from exc

    try:
        structured = parse_form_vision(page_images, api_key)
    except Exception as exc:
        raise RuntimeError(f"Claude Vision parse failed: {exc}") from exc

    try:
        form_id = save_to_db(structured, source_key, form_type)
    except Exception as exc:
        raise RuntimeError(f"DB save failed: {exc}") from exc

    return {"form_type": form_type, "form_id": form_id, **structured}
