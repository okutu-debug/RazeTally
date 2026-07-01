"""RazeTally REST API — browse at /docs (Swagger) or /redoc."""

import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, UploadFile

from db import get_db_connection
from form_types import FORM_TYPE_MAP, TALLY_CONFIG
from processor import process_pdf, save_upload

app = FastAPI(
    title="Raze Tally API",
    description="Query IEBC election form data parsed from PDFs.",
    version="0.1.0",
)

VALID_FORM_TYPES = list(FORM_TYPE_MAP.keys())


@contextmanager
def get_conn():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(conn, table_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (table_name,),
    )
    found = cursor.fetchone() is not None
    cursor.close()
    return found


def _query(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _resolve_form_type(form_type: str):
    key = form_type.lower()
    if key not in FORM_TYPE_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown form type '{form_type}'. Valid types: {VALID_FORM_TYPES}",
        )
    return key


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/form-types", summary="List all supported IEBC form types")
def list_form_types():
    return [
        {"form_type": k, "label": v[2], "forms_table": v[0], "votes_table": v[1]}
        for k, v in FORM_TYPE_MAP.items()
    ]


@app.get("/forms/{form_type}", summary="List parsed forms for a given form type")
def list_forms(
    form_type: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    county: str | None = Query(None, description="Filter by county name (partial match)"),
    constituency: str | None = Query(None, description="Filter by constituency name (partial match)"),
    ward: str | None = Query(None, description="Filter by ward name (partial match)"),
):
    key = _resolve_form_type(form_type)
    forms_table = FORM_TYPE_MAP[key][0]

    with get_conn() as conn:
        if not _table_exists(conn, forms_table):
            return []

        conditions = []
        params: list = []
        if county:
            conditions.append("county LIKE %s")
            params.append(f"%{county}%")
        if constituency:
            conditions.append("constituency LIKE %s")
            params.append(f"%{constituency}%")
        if ward:
            conditions.append("ward LIKE %s")
            params.append(f"%{ward}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params += [limit, offset]
        return _query(
            conn,
            f"SELECT * FROM `{forms_table}` {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params),
        )


@app.get("/forms/{form_type}/{form_id}", summary="Get a single form by ID")
def get_form(form_type: str, form_id: int):
    key = _resolve_form_type(form_type)
    forms_table = FORM_TYPE_MAP[key][0]

    with get_conn() as conn:
        if not _table_exists(conn, forms_table):
            raise HTTPException(status_code=404, detail="No data for this form type yet.")
        rows = _query(conn, f"SELECT * FROM `{forms_table}` WHERE id = %s", (form_id,))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Form {form_id} not found.")
        return rows[0]


@app.get("/votes/{form_type}", summary="List candidate votes for a given form type")
def list_votes(
    form_type: str,
    form_id: int | None = Query(None, description="Filter to a specific form"),
    candidate_name: str | None = Query(None, description="Partial match on candidate name"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    key = _resolve_form_type(form_type)
    votes_table = FORM_TYPE_MAP[key][1]

    with get_conn() as conn:
        if not _table_exists(conn, votes_table):
            return []

        conditions = []
        params: list = []
        if form_id is not None:
            conditions.append("form_id = %s")
            params.append(form_id)
        if candidate_name:
            conditions.append("candidate_name LIKE %s")
            params.append(f"%{candidate_name}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params += [limit, offset]
        return _query(
            conn,
            f"SELECT * FROM `{votes_table}` {where} ORDER BY votes DESC LIMIT %s OFFSET %s",
            tuple(params),
        )


@app.get("/tally/{form_type}", summary="Get aggregated tally for a given form type")
def get_tally(
    form_type: str,
    group_value: str | None = Query(
        None, description="Filter by county/constituency/ward code (depends on form type)"
    ),
    top: int | None = Query(None, ge=1, le=100, description="Return only top N candidates by votes"),
):
    key = _resolve_form_type(form_type)
    tally_table, group_key_col, _ = TALLY_CONFIG[key]

    with get_conn() as conn:
        if not _table_exists(conn, tally_table):
            return []

        conditions = []
        params: list = []
        if group_value and group_key_col:
            conditions.append(f"`{group_key_col}` = %s")
            params.append(group_value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = f"LIMIT {top}" if top else ""
        return _query(
            conn,
            f"SELECT * FROM `{tally_table}` {where} ORDER BY total_votes DESC {limit_clause}",
            tuple(params),
        )


@app.get("/tally/{form_type}/summary", summary="Summarised vote totals per candidate across all groups")
def tally_summary(form_type: str, top: int = Query(10, ge=1, le=100)):
    key = _resolve_form_type(form_type)
    tally_table, group_key_col, _ = TALLY_CONFIG[key]

    with get_conn() as conn:
        if not _table_exists(conn, tally_table):
            return []

        if group_key_col:
            sql = f"""
                SELECT candidate_number, candidate_name,
                       SUM(total_votes) AS total_votes,
                       SUM(total_registered) AS total_registered,
                       SUM(total_valid_votes) AS total_valid_votes,
                       SUM(total_rejected) AS total_rejected,
                       SUM(stations_counted) AS stations_counted
                FROM `{tally_table}`
                GROUP BY candidate_number, candidate_name
                ORDER BY total_votes DESC
                LIMIT %s
            """
        else:
            sql = f"""
                SELECT candidate_number, candidate_name,
                       total_votes, total_registered, total_valid_votes,
                       total_rejected, stations_counted
                FROM `{tally_table}`
                ORDER BY total_votes DESC
                LIMIT %s
            """
        return _query(conn, sql, (top,))


# ── Upload & background processing ───────────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(job_id: str, pdf_path: Path, api_key: str, force: bool):
    with _jobs_lock:
        _jobs[job_id]["status"] = "processing"
    try:
        result = process_pdf(pdf_path, api_key, force=force)
        with _jobs_lock:
            _jobs[job_id].update({"status": "done", "result": result})
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id].update({"status": "error", "error": str(exc)})


@app.post("/upload", summary="Upload a form (PDF/PNG/JPG/TIFF/BMP/WEBP) — saves to docs/forms/, parses with Claude, writes to DB")
async def upload_form(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-process even if already in DB"),
):
    ACCEPTED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
    if not file.filename or Path(file.filename).suffix.lower() not in ACCEPTED:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Accepted: {', '.join(sorted(ACCEPTED))}",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured on the server.")

    contents = await file.read()
    pdf_path = save_upload(contents, file.filename)

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending", "filename": file.filename}

    background_tasks.add_task(_run_job, job_id, pdf_path, api_key, force)
    return {"job_id": job_id, "status": "pending", "filename": file.filename}


@app.get("/jobs/{job_id}", summary="Poll the status of an upload processing job")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
