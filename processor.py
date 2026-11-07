"""Shared PDF processing pipeline: rasterize → Claude Vision → DB."""

import os
import shutil
import uuid
from pathlib import Path

import cloudinary_storage
from db import DOCS_DIR, find_duplicate_form_number, is_already_processed, save_to_db, user_can_access_station
from form_types import FORM_TYPE_CHOICES, FORM_TYPE_MAP, canonical_form_name, detect_form_type, normalize_form_type
from parser import parse_form_vision
from rasterizer import load_pages

FORMS_DIR = DOCS_DIR / "forms"


def save_upload(file_bytes: bytes, filename: str) -> Path:
    """Save uploaded bytes to FORMS_DIR and return the path.

    A short random suffix is added to the name: phone photos arrive with
    generic names (image.jpg, IMG_0001.jpg) that collide across agents, which
    would otherwise overwrite each other before parsing. Once the form is
    read, _extract() renames the file to its standard name
    (F35A-018-091-0454-017-02.pdf). The original name stays at the front
    until then, so a form code prefix like F35A-... still works as a hint."""
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name
    dest = FORMS_DIR / f"{Path(name).stem}-{uuid.uuid4().hex[:8]}{Path(name).suffix}"
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


def _rename_upload(path: Path, canonical: str) -> Path:
    """Rename an uploaded file to its standard name (e.g.
    F35A-018-091-0454-017-02.pdf), keeping the extension. If that name is
    already taken on disk (another upload for the same station still pending
    review, or a leftover from a failed save), add a short random suffix
    rather than overwrite it."""
    if path.stem == canonical:
        return path
    target = path.with_name(f"{canonical}{path.suffix.lower()}")
    if target.exists():
        target = path.with_name(f"{canonical}-{uuid.uuid4().hex[:8]}{path.suffix.lower()}")
    try:
        return path.rename(target)
    except OSError:
        return path  # keep the upload's own name rather than fail the parse


def _extract(pdf_path: Path, api_key: str, dpi: int, force: bool) -> tuple[str, str, dict]:
    """
    Rasterize + vision parse, then work out the form type, rename the file to
    its standard name and run the duplicate checks. Everything is read off
    the form itself (agents photograph forms and upload them without
    renaming); a filename prefix (F35A-...) is only a fallback for the type.
    Returns (form_type, source_key, structured).
    """
    filename_type = detect_form_type(pdf_path)

    try:
        page_images = load_pages(str(pdf_path), dpi=dpi)
    except Exception as exc:
        raise RuntimeError(f"Failed to rasterize '{pdf_path.name}': {exc}") from exc

    try:
        structured = parse_form_vision(page_images, api_key)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Vision parse failed: {exc}") from exc

    form_type = normalize_form_type(structured.pop("form_type", None)) or filename_type
    if form_type is None:
        raise ValueError(
            f"Could not determine the form type of '{pdf_path.name}'. Make sure the "
            f"form header (e.g. \"FORM 35A\") is clearly visible in the photo/scan, "
            f"or name the file starting with the form code ({FORM_TYPE_CHOICES})."
        )

    canonical = canonical_form_name(form_type, structured)
    if canonical and not force:
        # One form of each type per polling station: if a file with this
        # standard name is already stored, it's a re-upload.
        canonical_key = str((FORMS_DIR / f"{canonical}{pdf_path.suffix.lower()}").resolve())
        if is_already_processed(canonical_key, form_type):
            station = structured.get("polling_station") or structured.get("polling_station_code")
            raise ValueError(
                f"A Form {form_type.upper()} for polling station '{station}' ({canonical}) "
                "is already in the database. Tick 'Re-process if already in DB' to overwrite."
            )

    if canonical:
        pdf_path = _rename_upload(pdf_path, canonical)
    source_key = str(pdf_path.resolve())

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

    return form_type, source_key, structured


def parse_form(pdf_path: Path, api_key: str, dpi: int = 300, force: bool = False) -> dict:
    """
    Phase 1 — rasterize + Claude Vision parse only, no DB write.
    Returns the structured dict with extra keys 'form_type' and 'source_key'.
    """
    form_type, source_key, structured = _extract(pdf_path, api_key, dpi, force)
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
    Raises ValueError for unrecognisable forms, duplicates, or station access; RuntimeError
    on pipeline failures.
    """
    form_type, source_key, structured = _extract(pdf_path, api_key, dpi, force)

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
