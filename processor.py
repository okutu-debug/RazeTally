"""Shared PDF processing pipeline: rasterize → Claude Vision → DB."""

import os
import shutil
from pathlib import Path

import cloudinary_storage
from db import DOCS_DIR, find_duplicate_form_number, is_already_processed, save_to_db, user_can_access_station
from form_types import FORM_TYPE_MAP, detect_form_type
from parser import parse_form_vision
from rasterizer import load_pages

FORMS_DIR = DOCS_DIR / "forms"


def save_upload(file_bytes: bytes, filename: str) -> Path:
    """Save uploaded bytes to FORMS_DIR and return the path."""
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    dest = FORMS_DIR / filename
    dest.write_bytes(file_bytes)
    return dest


def _save_with_source(structured: dict, source_key: str, form_type: str, uploaded_by: str = "") -> int:
    """save_to_db, but with the source file moved to Cloudinary first so it
    survives on hosts with ephemeral disks. Falls back to storing the local
    path if Cloudinary isn't configured or the upload fails. The local copy is
    only deleted once the DB row is saved, so a failed save can be retried."""
    path = Path(source_key)
    stored = source_key
    if not cloudinary_storage.is_remote_ref(source_key) and path.exists():
        stored = cloudinary_storage.upload(path.read_bytes(), folder="razetally/forms", public_id=path.name) or source_key

    try:
        form_id = save_to_db(structured, stored, form_type, uploaded_by=uploaded_by)
    except Exception:
        if stored != source_key:
            cloudinary_storage.destroy(stored)
        raise

    if stored != source_key:
        path.unlink(missing_ok=True)
    return form_id


def parse_form(pdf_path: Path, api_key: str, dpi: int = 300, force: bool = False) -> dict:
    """
    Phase 1 — rasterize + Claude Vision parse only, no DB write.
    Returns the structured dict with extra keys 'form_type' and 'source_key'.
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
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Claude Vision parse failed: {exc}") from exc

    if not force:
        form_number = structured.get("form_number")
        duplicate = find_duplicate_form_number(form_number, form_type)
        if duplicate:
            existing_name = os.path.basename(duplicate["source_file"])
            raise ValueError(
                f"Form number '{form_number}' is already in the database "
                f"(uploaded previously as '{existing_name}'). "
                "Tick 'Re-process if already in DB' to overwrite."
            )

    return {"form_type": form_type, "source_key": source_key, **structured}


def commit_form(parsed: dict, uploaded_by: str = "") -> int:
    """Phase 2 — save a previously parsed form to the DB. Returns new form_id."""
    form_type  = parsed["form_type"]
    source_key = parsed["source_key"]
    structured = {k: v for k, v in parsed.items() if k not in ("form_type", "source_key")}

    if uploaded_by and not user_can_access_station(uploaded_by, structured.get("polling_station_code")):
        station_label = structured.get("polling_station") or structured.get("polling_station_code") or "this station"
        raise ValueError(
            f"You are not assigned to polling station '{station_label}'. "
            "Contact an admin to request access."
        )

    try:
        return _save_with_source(structured, source_key, form_type, uploaded_by=uploaded_by)
    except Exception as exc:
        raise RuntimeError(f"DB save failed: {exc}") from exc


def process_pdf(pdf_path: Path, api_key: str, dpi: int = 300, force: bool = False, uploaded_by: str = "") -> dict:
    """
    Full pipeline for one PDF: rasterize → Claude Vision → DB — no manual review
    step in between, unlike parse_form()/commit_form(). Used by the CLI and by
    the batch upload page, where reviewing each form individually isn't practical.
    Returns the structured result dict with an added 'form_type' key.
    Raises ValueError for bad filenames, duplicates, or station access; RuntimeError
    on pipeline failures.
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
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Claude Vision parse failed: {exc}") from exc

    if not force:
        form_number = structured.get("form_number")
        duplicate = find_duplicate_form_number(form_number, form_type)
        if duplicate:
            import os
            existing_name = os.path.basename(duplicate["source_file"])
            raise ValueError(
                f"Form number '{form_number}' is already in the database "
                f"(uploaded previously as '{existing_name}'). "
                "Tick 'Re-process if already in DB' to overwrite."
            )

    if uploaded_by and not user_can_access_station(uploaded_by, structured.get("polling_station_code")):
        station_label = structured.get("polling_station") or structured.get("polling_station_code") or "this station"
        raise ValueError(
            f"You are not assigned to polling station '{station_label}'. "
            "Contact an admin to request access."
        )

    try:
        form_id = _save_with_source(structured, source_key, form_type, uploaded_by=uploaded_by)
    except Exception as exc:
        raise RuntimeError(f"DB save failed: {exc}") from exc

    return {"form_type": form_type, "form_id": form_id, **structured}
