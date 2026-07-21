"""RazeTally REST API — browse at /docs (Swagger) or /redoc.

Endpoints are grouped into sections that mirror the app's sidebar navigation
(Dashboard, Demography, Recruitment, Membership, Campaign Mgt, Election Mgt,
Collaboration, Admin) so the two stay easy to cross-reference.
"""

import hashlib
import io
import mimetypes
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from PIL import Image
from pydantic import BaseModel, Field

from auth import SECRET_KEY, create_token, decode_token, verify_password
from db import (
    ACTIVITY_PRIORITIES,
    APPLICATION_STAGES,
    ATTACHMENT_REQUIREMENT_OPTIONS,
    CAMPAIGN_LOCATION_STATUSES,
    EVENT_TYPES,
    INTERVIEW_QUESTION_TYPES,
    OPINION_POLL_SOURCES,
    PANEL_ROLES,
    POSITION_TEAM_TYPES,
    RECURRENCE_FREQUENCIES,
    RECURRENCE_UNITS,
    TASK_STATUSES,
    accept_call,
    add_applicant_document,
    add_campaign_location,
    add_campaign_location_media,
    add_campaign_team,
    add_campaign_team_member,
    add_chat_group_members,
    add_constituency,
    add_county,
    add_election_team,
    add_election_team_member,
    add_event_member,
    add_ice_candidate,
    add_location_team_member,
    add_material,
    add_polling_station,
    add_position,
    add_user_document,
    add_ward,
    assign_election_material_to_team,
    assign_material_to_team,
    assign_user_polling_stations,
    assign_user_to_team,
    assigned_material_quantity,
    bulk_upsert_constituencies,
    bulk_upsert_counties,
    bulk_upsert_party_members,
    bulk_upsert_polling_stations,
    bulk_upsert_wards,
    cast_opinion_poll_vote,
    count_applications,
    count_applications_by_stage,
    count_campaign_locations,
    count_campaign_locations_by_publish_state,
    count_constituencies,
    count_counties,
    count_feed_posts,
    count_interview_questions,
    count_job_descriptions,
    count_job_descriptions_by_status,
    count_opinion_polls,
    count_opinion_polls_by_publish_state,
    count_panelists,
    count_party_members,
    count_polling_stations,
    count_users,
    count_users_by_team_type,
    count_wards,
    create_activity,
    create_application,
    create_call,
    create_chat_group,
    create_contribution,
    create_event,
    create_interview_question,
    create_job_description,
    create_opinion_poll,
    create_party_member,
    create_task,
    create_user,
    decline_call,
    delete_activity,
    delete_applicant_document,
    delete_application,
    delete_applications,
    delete_campaign_location,
    delete_campaign_location_media,
    delete_campaign_team,
    delete_constituency,
    delete_county,
    delete_election_team,
    delete_event,
    delete_interview_question,
    delete_job_description,
    delete_material,
    delete_opinion_poll,
    delete_party_member,
    delete_polling_station,
    delete_position,
    delete_task,
    delete_user,
    delete_user_document,
    delete_ward,
    end_call,
    get_active_call_for_user,
    get_activity,
    get_application,
    get_applicant_document,
    get_applicant_document_bytes,
    get_call,
    get_campaign_location,
    get_campaign_location_banner_bytes,
    get_campaign_location_media,
    get_campaign_location_media_bytes,
    get_campaign_team,
    get_candidate_photo_bytes,
    get_constituency,
    get_contribution,
    get_contribution_by_checkout_request_id,
    get_contribution_by_paypal_order_id,
    get_county,
    get_db_connection,
    get_election_team,
    get_event,
    get_feed_post_image_bytes,
    get_incoming_call,
    get_interview_question,
    get_job_description,
    get_material,
    get_opinion_poll,
    get_party_logo_bytes,
    get_party_member,
    get_polling_station,
    get_published_job_description_for_position,
    get_task,
    get_user,
    get_user_document,
    get_user_document_bytes,
    get_user_polling_station_codes,
    get_user_polling_stations,
    get_ward,
    init_activities,
    init_applicant_documents,
    init_applications,
    init_calls,
    init_campaign_location_media,
    init_campaign_locations,
    init_campaign_materials,
    init_campaign_teams,
    init_candidates,
    init_chat_groups,
    init_chat_messages,
    init_contributions,
    init_demography,
    init_election_materials,
    init_election_teams,
    init_events,
    init_feed,
    init_interview_answers,
    init_interview_questions,
    init_job_descriptions,
    init_location_team,
    init_materials,
    init_opinion_polls,
    init_panel_assignments,
    init_parties,
    init_party_members,
    init_polling_stations,
    init_positions,
    init_revoked_tokens,
    init_team_assignments,
    init_user_documents,
    init_user_polling_stations,
    init_users,
    is_panelist,
    list_activities_for_user,
    list_all_constituencies,
    list_all_counties,
    list_all_wards,
    list_applicant_documents,
    list_applications,
    list_campaign_location_media,
    list_campaign_locations,
    list_campaign_team_members,
    list_campaign_teams,
    list_candidates,
    list_chat_messages,
    list_constituencies,
    list_contributions,
    list_counties,
    list_dm_conversations,
    list_election_material_assignments,
    list_election_team_material_assignments,
    list_election_team_members,
    list_election_teams,
    list_event_members,
    list_events_for_user,
    list_feed_post_comments,
    list_feed_posts,
    list_group_chat_messages,
    list_group_members,
    list_ice_candidates,
    list_interview_qa_aggregated,
    list_interview_qa_for_panelist,
    list_interview_questions,
    list_job_descriptions,
    list_location_team_members,
    list_material_assignments,
    list_materials,
    list_opinion_poll_results,
    list_opinion_polls,
    list_panel_assignments_for_user,
    list_panelists,
    list_parties,
    list_party_members,
    list_polling_stations,
    list_positions,
    list_task_assignees,
    list_tasks_for_activity_and_user,
    list_team_assignments_for_user,
    list_team_material_assignments,
    list_user_documents,
    list_user_groups,
    list_users,
    list_users_by_team_type,
    list_wards,
    mark_call_missed,
    remove_campaign_location_banner,
    remove_campaign_team_member,
    remove_election_material_assignment,
    remove_election_team_member,
    remove_event_member,
    remove_location_team_member,
    remove_material_assignment,
    remove_user_from_team,
    save_applicant_document_file,
    save_campaign_media_file,
    save_user_document_file,
    send_chat_message,
    send_group_chat_message,
    set_campaign_location_banner,
    set_campaign_location_published,
    set_campaign_location_status,
    set_contribution_mpesa_request,
    set_contribution_paypal_order,
    set_job_description_published,
    set_opinion_poll_published,
    set_panelist_assignments,
    sum_completed_contributions,
    update_activity,
    update_application_profile,
    update_application_stage,
    update_applications_stage,
    update_campaign_location,
    update_campaign_team,
    update_constituency,
    update_contribution_status,
    update_county,
    update_election_team,
    update_event,
    update_interview_question,
    update_job_description,
    update_material,
    update_opinion_poll,
    update_party_member,
    update_password,
    update_polling_station,
    update_position,
    update_task,
    update_task_status,
    update_user_profile,
    update_ward,
    upsert_interview_answer,
)
from form_types import FORM_TYPE_MAP, TALLY_CONFIG
from mpesa import MpesaError, stk_push
from paypal import PayPalError, capture_order, create_order, get_approval_url
from processor import process_pdf, save_upload

app = FastAPI(
    title="Raze Tally API",
    description="Query IEBC election form data parsed from PDFs.",
    version="0.1.0",
)

# Only the origins listed here (comma-separated) can call the public endpoints
# from a browser — e.g. PUBLIC_CORS_ORIGINS=https://apply.yourparty.org
# Empty by default: no cross-origin browser access until explicitly configured.
_public_cors_origins = [
    o.strip() for o in os.environ.get("PUBLIC_CORS_ORIGINS", "").split(",") if o.strip()
]
if _public_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_public_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

VALID_FORM_TYPES = list(FORM_TYPE_MAP.keys())

# ── Bootstrap (self-provisions the schema; order matches viz_app.py's, which
# is the dependency-safe order — demography/users before anything that FKs
# into them) ──────────────────────────────────────────────────────────────────
init_demography()
init_users()
init_positions()
init_team_assignments()
init_panel_assignments()
init_polling_stations()
init_user_polling_stations()
init_user_documents()
init_applications()
init_applicant_documents()
init_job_descriptions()
init_interview_questions()
init_interview_answers()
init_materials()
init_campaign_teams()
init_campaign_materials()
init_campaign_locations()
init_location_team()
init_campaign_location_media()
init_election_teams()
init_election_materials()
init_chat_messages()
init_chat_groups()
init_calls()
init_events()
init_activities()
init_feed()
init_party_members()
init_parties()
init_candidates()
init_opinion_polls()
init_contributions()
init_revoked_tokens()

# ── Auth helpers ──────────────────────────────────────────────────────────────

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")
_oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_current_user(token: str = Depends(_oauth2)) -> dict:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return payload


def get_optional_user(token: str | None = Depends(_oauth2_optional)) -> dict | None:
    """Like get_current_user, but for endpoints that are also public: returns
    None instead of raising when there's no token or it's invalid/expired,
    so the endpoint can serve a reduced (public-safe) view to anonymous callers."""
    if not token:
        return None
    return decode_token(token)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user


# ── Rate limiting (public write endpoints only) ─────────────────────────────
# In-memory per-IP fixed window — resets on restart and doesn't share state
# across multiple instances. That's fine here: this defends against casual
# spam/flooding, not a security invariant (unlike auth revocation, which is
# DB-backed for exactly that reason). Trusts X-Forwarded-For when present, so
# put a reverse proxy that sets it (e.g. Nginx) in front in production —
# otherwise every request behind that proxy shares one bucket.
_rate_limit_buckets: dict[str, deque] = defaultdict(deque)
_rate_limit_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(key_prefix: str, max_requests: int, window_seconds: int):
    def _dependency(request: Request):
        key = f"{key_prefix}:{_client_ip(request)}"
        now = time.time()
        with _rate_limit_lock:
            bucket = _rate_limit_buckets[key]
            while bucket and bucket[0] < now - window_seconds:
                bucket.popleft()
            if len(bucket) >= max_requests:
                raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
            bucket.append(now)
    return _dependency


def _check_self_or_admin(current_user: dict, username: str) -> None:
    if current_user.get("role") != "admin" and current_user.get("sub") != username:
        raise HTTPException(status_code=403, detail="Not authorized for this user.")


def _public_user(user: dict) -> dict:
    """Strip the password hash before returning a user record over the API."""
    user = dict(user)
    user.pop("password_hash", None)
    return user


def _check_call_participant(current_user: dict, call: dict) -> None:
    if current_user["sub"] not in (call["caller_username"], call["callee_username"]):
        raise HTTPException(status_code=403, detail="Not a participant in this call.")


def _check_group_member(current_user: dict, group_id: int) -> None:
    my_groups = {g["id"] for g in list_user_groups(current_user["sub"])}
    if group_id not in my_groups:
        raise HTTPException(status_code=403, detail="Not a member of this group.")


def _check_event_owner_or_admin(current_user: dict, event: dict) -> None:
    if current_user.get("role") != "admin" and event.get("created_by") != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not authorized for this event.")


def _check_activity_owner_or_admin(current_user: dict, activity: dict) -> None:
    if current_user.get("role") != "admin" and activity.get("created_by") != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not authorized for this activity.")


def _check_task_owner_or_admin(current_user: dict, task: dict) -> None:
    if current_user.get("role") != "admin" and task.get("created_by") != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not authorized for this task.")


def _duplicate_or_bad_request(e: Exception) -> HTTPException:
    msg = str(e)
    if "Duplicate entry" in msg:
        return HTTPException(status_code=409, detail=msg)
    if "foreign key constraint fails" in msg:
        return HTTPException(
            status_code=400,
            detail="Referenced record does not exist (check position/ward/username/etc. are valid).",
        )
    return HTTPException(status_code=400, detail=msg)


@app.post("/auth/login", summary="Login — returns a Bearer token for protected endpoints", tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user(form.username)
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_token(user["username"], user["role"])
    return {"access_token": token, "token_type": "bearer"}


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


def _party_columns(conn, votes_alias: str, position_label: str, aggregate: bool) -> tuple[str, str, tuple]:
    """Builds a LEFT JOIN onto the admin-managed candidates/parties tables so a tally
    row can carry the candidate's party, matched by office + trimmed/uppercased name.
    Falls back to NULL columns if those tables haven't been provisioned yet."""
    if not _table_exists(conn, "candidates") or not _table_exists(conn, "parties"):
        return "", "NULL AS party_id, NULL AS party_name, NULL AS party_logo", ()
    wrap = (lambda c: f"MAX({c})") if aggregate else (lambda c: c)
    join_sql = (
        f"LEFT JOIN `candidates` cand ON cand.position = %s "
        f"AND UPPER(TRIM(cand.name)) = UPPER(TRIM({votes_alias}.candidate_name)) "
        f"LEFT JOIN `parties` prt ON prt.id = cand.party_id"
    )
    select_cols = (
        f"{wrap('cand.party_id')} AS party_id, "
        f"{wrap('prt.name')} AS party_name, "
        f"{wrap('prt.logo')} AS party_logo"
    )
    return join_sql, select_cols, (position_label,)


def _resolve_form_type(form_type: str):
    key = form_type.lower()
    if key not in FORM_TYPE_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown form type '{form_type}'. Valid types: {VALID_FORM_TYPES}",
        )
    return key


# ═══════════════════════════════════════════════════════════════════════════
# 📊 Dashboard — parsed form data, votes, tallies (mirrors the Dashboard page)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/form-types", summary="List all supported IEBC form types", tags=["Dashboard"])
def list_form_types():
    return [
        {"form_type": k, "label": v[2], "forms_table": v[0], "votes_table": v[1]}
        for k, v in FORM_TYPE_MAP.items()
    ]


@app.get("/forms/{form_type}", summary="List parsed forms for a given form type", tags=["Dashboard"])
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


@app.get(
    "/forms/{form_type}/locations",
    summary="Public: distinct counties/constituencies/wards that actually have data for this form "
    "type — used to narrow result-filter dropdowns down to locations with data instead of the full "
    "national reference lists.",
    tags=["Dashboard"],
)
def api_form_locations(form_type: str):
    key = _resolve_form_type(form_type)
    forms_table = FORM_TYPE_MAP[key][0]

    with get_conn() as conn:
        if not _table_exists(conn, forms_table):
            return {"counties": [], "constituencies": [], "wards": []}

        counties = _query(
            conn,
            f"""
            SELECT DISTINCT county_code AS code, county AS name
            FROM `{forms_table}`
            WHERE county_code IS NOT NULL AND county_code <> ''
            ORDER BY county
            """,
        )
        constituencies = _query(
            conn,
            f"""
            SELECT DISTINCT constituency_code AS code, constituency AS name
            FROM `{forms_table}`
            WHERE constituency_code IS NOT NULL AND constituency_code <> ''
            ORDER BY constituency
            """,
        )
        wards = _query(
            conn,
            f"""
            SELECT DISTINCT ward_code AS code, ward AS name
            FROM `{forms_table}`
            WHERE ward_code IS NOT NULL AND ward_code <> ''
            ORDER BY ward
            """,
        )
        return {"counties": counties, "constituencies": constituencies, "wards": wards}


@app.get("/forms/{form_type}/{form_id}", summary="Get a single form by ID", tags=["Dashboard"])
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


@app.get("/votes/{form_type}", summary="List candidate votes for a given form type", tags=["Dashboard"])
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


@app.get("/tally/{form_type}", summary="Get aggregated tally for a given form type", tags=["Dashboard"])
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


@app.get("/tally/{form_type}/summary", summary="Summarised vote totals per candidate across all groups", tags=["Dashboard"])
def tally_summary(form_type: str, top: int = Query(10, ge=1, le=100)):
    key = _resolve_form_type(form_type)
    tally_table, group_key_col, _ = TALLY_CONFIG[key]
    position_label = FORM_TYPE_MAP[key][2]

    with get_conn() as conn:
        if not _table_exists(conn, tally_table):
            return []

        party_join, party_cols, party_params = _party_columns(conn, "t", position_label, aggregate=bool(group_key_col))

        if group_key_col:
            sql = f"""
                SELECT t.candidate_number, t.candidate_name,
                       SUM(t.total_votes) AS total_votes,
                       SUM(t.total_registered) AS total_registered,
                       SUM(t.total_valid_votes) AS total_valid_votes,
                       SUM(t.total_rejected) AS total_rejected,
                       SUM(t.stations_counted) AS stations_counted,
                       {party_cols}
                FROM `{tally_table}` t
                {party_join}
                GROUP BY t.candidate_number, t.candidate_name
                ORDER BY total_votes DESC
                LIMIT %s
            """
        else:
            sql = f"""
                SELECT t.candidate_number, t.candidate_name,
                       t.total_votes, t.total_registered, t.total_valid_votes,
                       t.total_rejected, t.stations_counted,
                       {party_cols}
                FROM `{tally_table}` t
                {party_join}
                ORDER BY t.total_votes DESC
                LIMIT %s
            """
        return _query(conn, sql, (*party_params, top))


@app.get(
    "/tally/{form_type}/by-location",
    summary="Public: compute a tally on the fly filtered by county/constituency/ward code — "
    "unlike /tally/{form_type} (which only groups by the one geographic level baked into that "
    "office's precomputed tally table), this joins the raw forms+votes tables, which carry the "
    "full county/constituency/ward hierarchy for every form type.",
    tags=["Dashboard"],
)
def tally_by_location(
    form_type: str,
    county_code: str | None = Query(None),
    constituency_code: str | None = Query(None),
    ward_code: str | None = Query(None),
    top: int = Query(20, ge=1, le=100),
):
    key = _resolve_form_type(form_type)
    forms_table, votes_table, position_label = FORM_TYPE_MAP[key]

    with get_conn() as conn:
        if not _table_exists(conn, forms_table) or not _table_exists(conn, votes_table):
            return []

        party_join, party_cols, party_params = _party_columns(conn, "cv", position_label, aggregate=True)

        conditions = []
        params: list = []
        if county_code:
            conditions.append("f.county_code = %s")
            params.append(county_code)
        if constituency_code:
            conditions.append("f.constituency_code = %s")
            params.append(constituency_code)
        if ward_code:
            conditions.append("f.ward_code = %s")
            params.append(ward_code)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return _query(
            conn,
            f"""
            SELECT cv.candidate_number, cv.candidate_name,
                   SUM(cv.votes) AS total_votes,
                   COUNT(DISTINCT f.id) AS stations_counted,
                   {party_cols}
            FROM `{votes_table}` cv
            JOIN `{forms_table}` f ON f.id = cv.form_id
            {party_join}
            {where}
            GROUP BY cv.candidate_number, cv.candidate_name
            ORDER BY total_votes DESC
            LIMIT %s
            """,
            (*party_params, *params, top),
        )


@app.get("/parties", summary="Public: list all parties", tags=["Dashboard"])
def api_list_parties():
    return list_parties()


@app.get("/parties/{party_id}/logo", summary="Public: fetch a party's logo image", tags=["Dashboard"])
def api_get_party_logo(party_id: str):
    result = get_party_logo_bytes(party_id)
    if not result:
        raise HTTPException(status_code=404, detail="Logo not found.")
    file_bytes, display_name = result
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return Response(
        content=file_bytes, media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{display_name}"'},
    )


@app.get("/candidates", summary="Public: list candidates, optionally filtered by position/party/name", tags=["Dashboard"])
def api_list_candidates(
    search: str = Query("", description="Partial match on name/county/constituency/ward"),
    position: str | None = Query(None, description="Elective office, e.g. 'Member of National Assembly'"),
    party_id: str | None = Query(None),
):
    return list_candidates(search=search, position=position or "", party_id=party_id)


@app.get("/candidates/{candidate_id}/photo", summary="Public: fetch a candidate's photo", tags=["Dashboard"])
def api_get_candidate_photo(candidate_id: str):
    result = get_candidate_photo_bytes(candidate_id)
    if not result:
        raise HTTPException(status_code=404, detail="Photo not found.")
    file_bytes, display_name = result
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return Response(
        content=file_bytes, media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{display_name}"'},
    )


@app.get("/dashboard/summary", summary="Public: aggregate totals across all form types", tags=["Dashboard"])
def dashboard_summary(current_user: dict | None = Depends(get_optional_user)):
    total_forms = total_valid_votes = total_registered = total_rejected = 0
    form_types_with_data = 0
    with get_conn() as conn:
        for _key, (forms_tbl, _votes_tbl, _label) in FORM_TYPE_MAP.items():
            if not _table_exists(conn, forms_tbl):
                continue
            rows = _query(
                conn,
                f"""
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(total_valid_votes), 0) AS valid_votes,
                       COALESCE(SUM(registered_voters), 0) AS registered,
                       COALESCE(SUM(rejected_ballots), 0) AS rejected
                FROM `{forms_tbl}`
                """,
            )
            row = rows[0] if rows else None
            if row and row["n"]:
                total_forms       += row["n"]
                total_valid_votes += row["valid_votes"]
                total_registered  += row["registered"]
                total_rejected    += row["rejected"]
                form_types_with_data += 1
    return {
        "total_forms":       total_forms,
        "form_types":        form_types_with_data,
        "form_types_total":  len(FORM_TYPE_MAP),
        "total_valid_votes": total_valid_votes,
        "total_registered":  total_registered,
        "total_rejected":    total_rejected,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 🗺️ Demography — counties, constituencies, wards, polling stations
# ═══════════════════════════════════════════════════════════════════════════

class CountyIn(BaseModel):
    county_id: str
    county_name: str


class CountyBulkIn(BaseModel):
    counties: list[CountyIn]


class ConstituencyIn(BaseModel):
    constituency_id: str
    constituency_name: str
    county_id: str


class ConstituencyBulkIn(BaseModel):
    constituencies: list[ConstituencyIn]


class WardIn(BaseModel):
    ward_id: str
    ward_name: str
    constituency_id: str


class WardBulkIn(BaseModel):
    wards: list[WardIn]


class PollingStationIn(BaseModel):
    county: str = ""
    county_code: str = ""
    constituency: str = ""
    constituency_code: str = ""
    ward: str = ""
    ward_code: str = ""
    polling_station_code: str
    polling_station_name: str
    registered_voters: int = 0


class PollingStationBulkIn(BaseModel):
    stations: list[PollingStationIn]


@app.get("/counties", summary="List/search counties", tags=["Demography"])
def api_list_counties(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_counties(search),
        "items": list_counties(search, limit=limit, offset=offset),
    }


@app.get(
    "/counties/all",
    summary="Public: unpaginated county list (for dropdowns, e.g. the outward-facing apply/join forms)",
    tags=["Demography"],
)
def api_list_all_counties():
    return list_all_counties()


@app.get("/counties/{county_id}", summary="Get a single county", tags=["Demography"])
def api_get_county(county_id: str, current_user: dict = Depends(get_current_user)):
    county = get_county(county_id)
    if not county:
        raise HTTPException(status_code=404, detail="County not found.")
    return county


@app.post("/counties", summary="Create a county (admin only)", tags=["Demography"])
def api_add_county(body: CountyIn, current_user: dict = Depends(require_admin)):
    try:
        add_county(body.county_id, body.county_name)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_county(body.county_id)


@app.put("/counties/{county_id}", summary="Update a county (admin only)", tags=["Demography"])
def api_update_county(county_id: str, body: CountyIn, current_user: dict = Depends(require_admin)):
    if not get_county(county_id):
        raise HTTPException(status_code=404, detail="County not found.")
    try:
        update_county(county_id, body.county_id, body.county_name)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_county(body.county_id)


@app.delete("/counties/{county_id}", summary="Delete a county (admin only)", tags=["Demography"])
def api_delete_county(county_id: str, current_user: dict = Depends(require_admin)):
    delete_county(county_id)
    return {"deleted": county_id}


@app.post("/counties/bulk", summary="Bulk insert/update counties (admin only)", tags=["Demography"])
def api_bulk_counties(body: CountyBulkIn, current_user: dict = Depends(require_admin)):
    rows = [c.model_dump() for c in body.counties]
    inserted, updated = bulk_upsert_counties(rows)
    return {"inserted": inserted, "updated": updated}


@app.get("/constituencies", summary="List/search constituencies", tags=["Demography"])
def api_list_constituencies(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_constituencies(search),
        "items": list_constituencies(search, limit=limit, offset=offset),
    }


@app.get(
    "/constituencies/all",
    summary="Public: unpaginated constituency list (for dropdowns, e.g. the outward-facing apply/join forms)",
    tags=["Demography"],
)
def api_list_all_constituencies():
    return list_all_constituencies()


@app.get("/constituencies/{constituency_id}", summary="Get a single constituency", tags=["Demography"])
def api_get_constituency(constituency_id: str, current_user: dict = Depends(get_current_user)):
    constituency = get_constituency(constituency_id)
    if not constituency:
        raise HTTPException(status_code=404, detail="Constituency not found.")
    return constituency


@app.post("/constituencies", summary="Create a constituency (admin only)", tags=["Demography"])
def api_add_constituency(body: ConstituencyIn, current_user: dict = Depends(require_admin)):
    try:
        add_constituency(body.constituency_id, body.constituency_name, body.county_id)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_constituency(body.constituency_id)


@app.put("/constituencies/{constituency_id}", summary="Update a constituency (admin only)", tags=["Demography"])
def api_update_constituency(
    constituency_id: str, body: ConstituencyIn, current_user: dict = Depends(require_admin),
):
    if not get_constituency(constituency_id):
        raise HTTPException(status_code=404, detail="Constituency not found.")
    try:
        update_constituency(constituency_id, body.constituency_id, body.constituency_name, body.county_id)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_constituency(body.constituency_id)


@app.delete("/constituencies/{constituency_id}", summary="Delete a constituency (admin only)", tags=["Demography"])
def api_delete_constituency(constituency_id: str, current_user: dict = Depends(require_admin)):
    delete_constituency(constituency_id)
    return {"deleted": constituency_id}


@app.post("/constituencies/bulk", summary="Bulk insert/update constituencies (admin only)", tags=["Demography"])
def api_bulk_constituencies(body: ConstituencyBulkIn, current_user: dict = Depends(require_admin)):
    rows = [c.model_dump() for c in body.constituencies]
    inserted, updated = bulk_upsert_constituencies(rows)
    return {"inserted": inserted, "updated": updated}


@app.get("/wards", summary="List/search wards", tags=["Demography"])
def api_list_wards(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_wards(search),
        "items": list_wards(search, limit=limit, offset=offset),
    }


@app.get(
    "/wards/all",
    summary="Public: unpaginated ward list (for dropdowns, e.g. the outward-facing apply/join forms)",
    tags=["Demography"],
)
def api_list_all_wards():
    return list_all_wards()


@app.get("/wards/{ward_id}", summary="Get a single ward", tags=["Demography"])
def api_get_ward(ward_id: str, current_user: dict = Depends(get_current_user)):
    ward = get_ward(ward_id)
    if not ward:
        raise HTTPException(status_code=404, detail="Ward not found.")
    return ward


@app.post("/wards", summary="Create a ward (admin only)", tags=["Demography"])
def api_add_ward(body: WardIn, current_user: dict = Depends(require_admin)):
    try:
        add_ward(body.ward_id, body.ward_name, body.constituency_id)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_ward(body.ward_id)


@app.put("/wards/{ward_id}", summary="Update a ward (admin only)", tags=["Demography"])
def api_update_ward(ward_id: str, body: WardIn, current_user: dict = Depends(require_admin)):
    if not get_ward(ward_id):
        raise HTTPException(status_code=404, detail="Ward not found.")
    try:
        update_ward(ward_id, body.ward_id, body.ward_name, body.constituency_id)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_ward(body.ward_id)


@app.delete("/wards/{ward_id}", summary="Delete a ward (admin only)", tags=["Demography"])
def api_delete_ward(ward_id: str, current_user: dict = Depends(require_admin)):
    delete_ward(ward_id)
    return {"deleted": ward_id}


@app.post("/wards/bulk", summary="Bulk insert/update wards (admin only)", tags=["Demography"])
def api_bulk_wards(body: WardBulkIn, current_user: dict = Depends(require_admin)):
    rows = [w.model_dump() for w in body.wards]
    inserted, updated = bulk_upsert_wards(rows)
    return {"inserted": inserted, "updated": updated}


@app.get("/polling-stations", summary="List/search polling stations", tags=["Demography"])
def api_list_polling_stations(
    search: str = Query("", description="Search county/constituency/ward/name/code"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_polling_stations(search),
        "items": list_polling_stations(search, limit=limit, offset=offset),
    }


@app.get("/polling-stations/{code}", summary="Get a single polling station", tags=["Demography"])
def api_get_polling_station(code: str, current_user: dict = Depends(get_current_user)):
    station = get_polling_station(code)
    if not station:
        raise HTTPException(status_code=404, detail="Polling station not found.")
    return station


@app.post("/polling-stations", summary="Create a polling station (admin only)", tags=["Demography"])
def api_add_polling_station(body: PollingStationIn, current_user: dict = Depends(require_admin)):
    try:
        add_polling_station(**body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_polling_station(body.polling_station_code)


@app.put("/polling-stations/{code}", summary="Update a polling station (admin only)", tags=["Demography"])
def api_update_polling_station(code: str, body: PollingStationIn, current_user: dict = Depends(require_admin)):
    if not get_polling_station(code):
        raise HTTPException(status_code=404, detail="Polling station not found.")
    try:
        update_polling_station(code, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_polling_station(body.polling_station_code)


@app.delete("/polling-stations/{code}", summary="Delete a polling station (admin only)", tags=["Demography"])
def api_delete_polling_station(code: str, current_user: dict = Depends(require_admin)):
    delete_polling_station(code)
    return {"deleted": code}


@app.post("/polling-stations/bulk", summary="Bulk insert/update polling stations (admin only)", tags=["Demography"])
def api_bulk_polling_stations(body: PollingStationBulkIn, current_user: dict = Depends(require_admin)):
    rows = [s.model_dump() for s in body.stations]
    inserted, updated = bulk_upsert_polling_stations(rows)
    return {"inserted": inserted, "updated": updated}


# ═══════════════════════════════════════════════════════════════════════════
# 🧑‍💼 Recruitment — job descriptions, applications, interviews, panelists
# ═══════════════════════════════════════════════════════════════════════════

class JobDescriptionIn(BaseModel):
    position: str
    description: str = ""
    num_applicants_required: int = 1
    application_deadline: date | None = None
    attachment_requirements: list[str] = []


class ApplicationIn(BaseModel):
    other_names: str = ""
    surname: str = ""
    email: str = ""
    position: str = ""
    id_passport_number: str = ""
    phone_number: str = ""
    gender: str = ""
    date_of_birth: date | None = None
    county: str = ""
    sub_county: str = ""
    ward: str = ""
    ward_id: str | None = None


class ApplicationBulkDeleteIn(BaseModel):
    ids: list[str]


class ApplicationStageIn(BaseModel):
    stage: str


class ApplicationsBulkStageIn(BaseModel):
    ids: list[str]
    stage: str


class InterviewQuestionIn(BaseModel):
    position: str
    question: str
    question_type: str = "oral"


class InterviewAnswerIn(BaseModel):
    answer: str


class PanelAssignmentIn(BaseModel):
    position: str
    panel_role: str = "member"
    interview_date: date | None = None


class PanelistAssignmentsIn(BaseModel):
    assignments: list[PanelAssignmentIn]


@app.get(
    "/job-descriptions",
    summary="Public: list/search job descriptions (anonymous callers only ever see published ones)",
    tags=["Recruitment"],
)
def api_list_job_descriptions(
    search: str = Query(""),
    published: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict | None = Depends(get_optional_user),
):
    if current_user is None:
        published = True  # anonymous callers never see drafts, regardless of what they asked for
    return {
        "total": count_job_descriptions(search, published),
        "items": list_job_descriptions(search, published, limit=limit, offset=offset),
    }


@app.get("/job-descriptions/status-counts", summary="Published/draft counts", tags=["Recruitment"])
def api_job_description_status_counts(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return count_job_descriptions_by_status(search)


@app.get(
    "/job-descriptions/for-position/{position}",
    summary="Public: get the currently published job description for a position, if any",
    tags=["Recruitment"],
)
def api_job_description_for_position(position: str, current_user: dict | None = Depends(get_optional_user)):
    # Already published-only by construction — safe for anonymous callers as-is.
    jd = get_published_job_description_for_position(position)
    if not jd:
        raise HTTPException(status_code=404, detail="No published job description for this position.")
    return jd


@app.get(
    "/job-descriptions/{id}",
    summary="Public: get a single job description (anonymous callers can only see published ones)",
    tags=["Recruitment"],
)
def api_get_job_description(id: str, current_user: dict | None = Depends(get_optional_user)):
    jd = get_job_description(id)
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found.")
    if current_user is None and not jd.get("published"):
        raise HTTPException(status_code=404, detail="Job description not found.")
    return jd


def _check_attachment_requirements(items: list[str]) -> None:
    invalid = [i for i in items if i not in ATTACHMENT_REQUIREMENT_OPTIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid attachment_requirements {invalid}. Valid: {ATTACHMENT_REQUIREMENT_OPTIONS}",
        )


@app.post("/job-descriptions", summary="Create a job description (admin only)", tags=["Recruitment"])
def api_create_job_description(body: JobDescriptionIn, current_user: dict = Depends(require_admin)):
    _check_attachment_requirements(body.attachment_requirements)
    try:
        new_id = create_job_description(**body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_job_description(str(new_id))


@app.put("/job-descriptions/{id}", summary="Update a job description (admin only)", tags=["Recruitment"])
def api_update_job_description(id: str, body: JobDescriptionIn, current_user: dict = Depends(require_admin)):
    if not get_job_description(id):
        raise HTTPException(status_code=404, detail="Job description not found.")
    _check_attachment_requirements(body.attachment_requirements)
    try:
        update_job_description(id, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_job_description(id)


@app.delete("/job-descriptions/{id}", summary="Delete a job description (admin only)", tags=["Recruitment"])
def api_delete_job_description(id: str, current_user: dict = Depends(require_admin)):
    delete_job_description(id)
    return {"deleted": id}


@app.put("/job-descriptions/{id}/publish", summary="Publish/unpublish a job description (admin only)", tags=["Recruitment"])
def api_publish_job_description(id: str, published: bool = Query(...), current_user: dict = Depends(require_admin)):
    if not get_job_description(id):
        raise HTTPException(status_code=404, detail="Job description not found.")
    set_job_description_published(id, published)
    return get_job_description(id)


@app.get("/applications", summary="List/search applications", tags=["Recruitment"])
def api_list_applications(
    search: str = Query(""),
    stage: str | None = Query(None),
    positions: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_applications(search, stage, positions),
        "items": list_applications(search, limit=limit, offset=offset, stage=stage, positions=positions),
    }


@app.get("/applications/stage-counts", summary="Application counts per pipeline stage", tags=["Recruitment"])
def api_application_stage_counts(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return count_applications_by_stage(search)


@app.get("/applications/{id}", summary="Get a single application", tags=["Recruitment"])
def api_get_application(id: str, current_user: dict = Depends(get_current_user)):
    application = get_application(id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application


@app.post("/applications", summary="Create an application (admin only)", tags=["Recruitment"])
def api_create_application(body: ApplicationIn, current_user: dict = Depends(require_admin)):
    try:
        new_id = create_application(**body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_application(str(new_id))


_APPLY_ACCEPTED_ATTACHMENTS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"}
_APPLY_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB per file

_CAMPAIGN_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_CAMPAIGN_IMAGE_MAX_BYTES = 8 * 1024 * 1024  # 8MB per image


def _validate_campaign_image(filename: str, contents: bytes) -> None:
    if Path(filename).suffix.lower() not in _CAMPAIGN_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type for '{filename}'. "
                   f"Accepted: {', '.join(sorted(_CAMPAIGN_IMAGE_EXTENSIONS))}",
        )
    if len(contents) > _CAMPAIGN_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"'{filename}' exceeds the 8MB image limit.")
    try:
        Image.open(io.BytesIO(contents)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail=f"'{filename}' is not a valid image.")


@app.post(
    "/apply",
    summary="Public: submit a job application, with optional CV/ID/certificate attachments, in one request",
    tags=["Recruitment"],
)
async def apply_public(
    position: str = Form(...),
    surname: str = Form(""),
    other_names: str = Form(""),
    email: str = Form(""),
    id_passport_number: str = Form(""),
    phone_number: str = Form(""),
    gender: str = Form(""),
    date_of_birth: date | None = Form(None),
    county: str = Form(""),
    sub_county: str = Form(""),
    ward: str = Form(""),
    cv: UploadFile | None = File(None, description="Curriculum Vitae"),
    id_document: UploadFile | None = File(None, description="National ID or Passport copy"),
    certificate: UploadFile | None = File(None, description="Academic/professional certificate"),
    other_document: UploadFile | None = File(None, description="Any other supporting document"),
    _rl: None = Depends(rate_limit("apply", max_requests=5, window_seconds=3600)),
):
    attachments = [
        (title, f) for title, f in [
            ("CV", cv), ("ID Document", id_document),
            ("Certificate", certificate), ("Other Document", other_document),
        ] if f is not None and f.filename
    ]

    if not get_published_job_description_for_position(position):
        raise HTTPException(
            status_code=400,
            detail="This position isn't currently open for applications.",
        )
    for _title, f in attachments:
        if Path(f.filename).suffix.lower() not in _APPLY_ACCEPTED_ATTACHMENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported attachment type for '{f.filename}'. "
                       f"Accepted: {', '.join(sorted(_APPLY_ACCEPTED_ATTACHMENTS))}",
            )

    try:
        new_id = create_application(
            other_names=other_names, surname=surname, email=email, position=position,
            id_passport_number=id_passport_number, phone_number=phone_number, gender=gender,
            date_of_birth=date_of_birth, county=county, sub_county=sub_county, ward=ward,
        )
    except Exception as e:
        raise _duplicate_or_bad_request(e)

    for title, f in attachments:
        contents = await f.read()
        if len(contents) > _APPLY_MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail=f"'{f.filename}' exceeds the 10MB attachment limit.")
        stored_name = save_applicant_document_file(new_id, f.filename, contents)
        add_applicant_document(new_id, title, stored_name, f.filename, "applicant")

    return get_application(str(new_id))


@app.put("/applications/{id}", summary="Update an application (admin only)", tags=["Recruitment"])
def api_update_application(id: str, body: ApplicationIn, current_user: dict = Depends(require_admin)):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    try:
        update_application_profile(id, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_application(id)


@app.delete("/applications/{id}", summary="Delete an application (admin only)", tags=["Recruitment"])
def api_delete_application(id: str, current_user: dict = Depends(require_admin)):
    delete_application(id)
    return {"deleted": id}


@app.post("/applications/bulk-delete", summary="Delete multiple applications (admin only)", tags=["Recruitment"])
def api_bulk_delete_applications(body: ApplicationBulkDeleteIn, current_user: dict = Depends(require_admin)):
    delete_applications(body.ids)
    return {"deleted": body.ids}


@app.put("/applications/{id}/stage", summary="Move an application to a different pipeline stage (admin only)", tags=["Recruitment"])
def api_update_application_stage(id: str, body: ApplicationStageIn, current_user: dict = Depends(require_admin)):
    if body.stage not in APPLICATION_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Valid stages: {APPLICATION_STAGES}")
    update_application_stage(id, body.stage)
    return get_application(id)


@app.put("/applications/bulk-stage", summary="Move multiple applications to a stage (admin only)", tags=["Recruitment"])
def api_bulk_update_application_stage(body: ApplicationsBulkStageIn, current_user: dict = Depends(require_admin)):
    if body.stage not in APPLICATION_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Valid stages: {APPLICATION_STAGES}")
    update_applications_stage(body.ids, body.stage)
    return {"updated": body.ids, "stage": body.stage}


@app.get("/applications/{id}/documents", summary="List an application's attached documents (admin only)", tags=["Recruitment"])
def api_list_applicant_documents(id: str, current_user: dict = Depends(require_admin)):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    return list_applicant_documents(id)


@app.post("/applications/{id}/documents", summary="Attach a document to an application (admin only)", tags=["Recruitment"])
async def api_upload_applicant_document(
    id: str,
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_admin),
):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    if not title.strip() or not file.filename:
        raise HTTPException(status_code=400, detail="A title and a file are both required.")
    contents = await file.read()
    stored_name = save_applicant_document_file(id, file.filename, contents)
    doc_id = add_applicant_document(id, title.strip(), stored_name, file.filename, current_user["sub"])
    return {"id": doc_id, "application_id": id, "title": title.strip(), "original_filename": file.filename}


@app.get("/applicant-documents/{doc_id}/download", summary="Download an applicant document (admin only)", tags=["Recruitment"])
def api_download_applicant_document(doc_id: int, current_user: dict = Depends(require_admin)):
    doc = get_applicant_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    result = get_applicant_document_bytes(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document file is missing on disk.")
    file_bytes, display_name = result
    return Response(
        content=file_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{display_name}"'},
    )


@app.delete("/applicant-documents/{doc_id}", summary="Delete an applicant document (admin only)", tags=["Recruitment"])
def api_delete_applicant_document(doc_id: int, current_user: dict = Depends(require_admin)):
    doc = get_applicant_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    delete_applicant_document(doc_id)
    return {"deleted": doc_id}


@app.get("/interview-questions", summary="List/search interview questions", tags=["Recruitment"])
def api_list_interview_questions(
    search: str = Query(""),
    position: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_interview_questions(search, position),
        "items": list_interview_questions(search, position, limit=limit, offset=offset),
    }


@app.get("/interview-questions/{id}", summary="Get a single interview question", tags=["Recruitment"])
def api_get_interview_question(id: str, current_user: dict = Depends(get_current_user)):
    question = get_interview_question(id)
    if not question:
        raise HTTPException(status_code=404, detail="Interview question not found.")
    return question


@app.post("/interview-questions", summary="Create an interview question (admin only)", tags=["Recruitment"])
def api_create_interview_question(body: InterviewQuestionIn, current_user: dict = Depends(require_admin)):
    if body.question_type not in INTERVIEW_QUESTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid question_type. Valid: {INTERVIEW_QUESTION_TYPES}")
    try:
        new_id = create_interview_question(body.position, body.question, body.question_type)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_interview_question(str(new_id))


@app.put("/interview-questions/{id}", summary="Update an interview question (admin only)", tags=["Recruitment"])
def api_update_interview_question(id: str, body: InterviewQuestionIn, current_user: dict = Depends(require_admin)):
    if not get_interview_question(id):
        raise HTTPException(status_code=404, detail="Interview question not found.")
    if body.question_type not in INTERVIEW_QUESTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid question_type. Valid: {INTERVIEW_QUESTION_TYPES}")
    try:
        update_interview_question(id, body.position, body.question, body.question_type)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_interview_question(id)


@app.delete("/interview-questions/{id}", summary="Delete an interview question (admin only)", tags=["Recruitment"])
def api_delete_interview_question(id: str, current_user: dict = Depends(require_admin)):
    delete_interview_question(id)
    return {"deleted": id}


@app.get(
    "/applications/{id}/interview-answers",
    summary="Aggregated interview Q&A for an application across all panelists (admin only)", tags=["Recruitment"],
)
def api_interview_qa_aggregated(id: str, position: str = Query(...), current_user: dict = Depends(require_admin)):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    return list_interview_qa_aggregated(id, position)


@app.get(
    "/applications/{id}/interview-answers/mine",
    summary="Your own interview answers for an application (panelist self-service)", tags=["Recruitment"],
)
def api_interview_qa_mine(id: str, position: str = Query(...), current_user: dict = Depends(get_current_user)):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    return list_interview_qa_for_panelist(id, position, current_user["sub"])


@app.put(
    "/applications/{id}/interview-answers/{question_id}",
    summary="Record your own answer to an interview question (panelist self-service)", tags=["Recruitment"],
)
def api_upsert_interview_answer(
    id: str, question_id: str, body: InterviewAnswerIn, current_user: dict = Depends(get_current_user),
):
    if not get_application(id):
        raise HTTPException(status_code=404, detail="Application not found.")
    upsert_interview_answer(id, question_id, body.answer, current_user["sub"])
    return {"application_id": id, "question_id": question_id, "answered_by": current_user["sub"]}


@app.get("/panelists", summary="List/search panelists (admin only)", tags=["Recruitment"])
def api_list_panelists(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_admin),
):
    return {
        "total": count_panelists(search),
        "items": list_panelists(search, limit=limit, offset=offset),
    }


@app.get("/panelists/{username}", summary="Get a panelist's position assignments (admin or self)", tags=["Recruitment"])
def api_get_panelist(username: str, current_user: dict = Depends(get_current_user)):
    _check_self_or_admin(current_user, username)
    if not is_panelist(username):
        raise HTTPException(status_code=404, detail="This user has no panel assignments.")
    return list_panel_assignments_for_user(username)


@app.put("/panelists/{username}/assignments", summary="Replace a panelist's position assignments (admin only)", tags=["Recruitment"])
def api_set_panelist_assignments(
    username: str, body: PanelistAssignmentsIn, current_user: dict = Depends(require_admin),
):
    for a in body.assignments:
        if a.panel_role not in PANEL_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid panel_role. Valid: {PANEL_ROLES}")
    set_panelist_assignments(username, [a.model_dump() for a in body.assignments])
    return list_panel_assignments_for_user(username)


# ═══════════════════════════════════════════════════════════════════════════
# 🧑‍🤝‍🧑 Membership — party members
# ═══════════════════════════════════════════════════════════════════════════

class PartyMemberIn(BaseModel):
    name: str
    id_number: str
    email: str = ""
    phone_number: str = ""
    age: int | None = None
    gender: str = ""
    county: str = ""
    constituency: str = ""
    ward: str = ""
    ward_id: str | None = None


class PartyMemberBulkIn(BaseModel):
    members: list[PartyMemberIn]


@app.get("/party-members", summary="List/search party members", tags=["Membership"])
def api_list_party_members(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_party_members(search),
        "items": list_party_members(search, limit=limit, offset=offset),
    }


@app.get("/party-members/{id}", summary="Get a single party member", tags=["Membership"])
def api_get_party_member(id: str, current_user: dict = Depends(get_current_user)):
    member = get_party_member(id)
    if not member:
        raise HTTPException(status_code=404, detail="Party member not found.")
    return member


@app.post(
    "/party-members",
    summary="Public: register as a party member",
    tags=["Membership"],
)
def api_create_party_member(
    body: PartyMemberIn,
    _rl: None = Depends(rate_limit("party_member_signup", max_requests=5, window_seconds=3600)),
):
    try:
        new_id = create_party_member(**body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_party_member(str(new_id))


@app.put("/party-members/{id}", summary="Update a party member (admin only)", tags=["Membership"])
def api_update_party_member(id: str, body: PartyMemberIn, current_user: dict = Depends(require_admin)):
    if not get_party_member(id):
        raise HTTPException(status_code=404, detail="Party member not found.")
    try:
        update_party_member(id, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_party_member(id)


@app.delete("/party-members/{id}", summary="Delete a party member (admin only)", tags=["Membership"])
def api_delete_party_member(id: str, current_user: dict = Depends(require_admin)):
    delete_party_member(id)
    return {"deleted": id}


@app.post("/party-members/bulk", summary="Bulk insert/update party members, matched by id_number (admin only)", tags=["Membership"])
def api_bulk_party_members(body: PartyMemberBulkIn, current_user: dict = Depends(require_admin)):
    rows = [m.model_dump() for m in body.members]
    inserted, updated = bulk_upsert_party_members(rows)
    return {"inserted": inserted, "updated": updated}


class MpesaContributionIn(BaseModel):
    contributor_name: str
    phone_number: str
    amount: float = Field(gt=0, le=1_000_000)


class PayPalContributionIn(BaseModel):
    contributor_name: str
    email: str
    amount: float = Field(gt=0, le=100_000)


class PayPalOrderRefIn(BaseModel):
    order_id: str


def _public_contribution(c: dict) -> dict:
    """Strip internal/PII fields (phone_number, email, recorded_by, request ids)
    before returning a contribution over the public API."""
    return {
        "id": c["id"],
        "status": c["status"],
        "amount": float(c["amount"]),
        "currency": c["currency"],
        "payment_method": c["payment_method"],
        "mpesa_receipt_number": c.get("mpesa_receipt_number"),
        "result_desc": c.get("result_desc"),
    }


def _outward_facing_base_url() -> str:
    url = os.environ.get("OUTWARD_FACING_URL", "").strip().rstrip("/")
    if not url:
        raise HTTPException(
            status_code=500,
            detail="PayPal donations aren't configured (OUTWARD_FACING_URL is unset).",
        )
    return url


@app.post(
    "/contributions/mpesa",
    summary="Public: contribute to the campaign via M-Pesa — sends an STK push to the given phone",
    tags=["Membership"],
)
def api_contribute_mpesa(
    body: MpesaContributionIn,
    _rl: None = Depends(rate_limit("contribute_mpesa", max_requests=5, window_seconds=3600)),
):
    contribution_id = create_contribution(
        contributor_name=body.contributor_name, amount=body.amount, currency="KES",
        payment_method="mpesa", phone_number=body.phone_number,
    )
    try:
        result = stk_push(
            body.phone_number, int(body.amount),
            account_reference=f"CONTRIB{contribution_id}", transaction_desc="Contribution",
        )
        set_contribution_mpesa_request(
            contribution_id, result.get("MerchantRequestID", ""), result.get("CheckoutRequestID", ""),
        )
    except MpesaError as e:
        update_contribution_status(contribution_id, "failed", result_desc=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    return _public_contribution(get_contribution(contribution_id))


@app.get(
    "/contributions/mpesa/{id}",
    summary="Public: poll an M-Pesa contribution's status while awaiting the STK push result",
    tags=["Membership"],
)
def api_mpesa_contribution_status(id: int):
    contribution = get_contribution(id)
    if not contribution or contribution["payment_method"] != "mpesa":
        raise HTTPException(status_code=404, detail="Contribution not found.")
    return _public_contribution(contribution)


@app.post(
    "/contributions/paypal",
    summary="Public: contribute to the campaign via PayPal — returns an approval URL to redirect to",
    tags=["Membership"],
)
def api_contribute_paypal(
    body: PayPalContributionIn,
    _rl: None = Depends(rate_limit("contribute_paypal", max_requests=5, window_seconds=3600)),
):
    contribution_id = create_contribution(
        contributor_name=body.contributor_name, amount=body.amount, currency="USD",
        payment_method="paypal", email=body.email,
    )
    base_url = _outward_facing_base_url()
    try:
        order = create_order(
            amount=body.amount, currency="USD",
            return_url=f"{base_url}/donate?paypal_action=return",
            cancel_url=f"{base_url}/donate?paypal_action=cancel",
            reference_id=str(contribution_id),
            description=f"Contribution from {body.contributor_name}",
        )
        set_contribution_paypal_order(contribution_id, order["id"])
        approval_url = get_approval_url(order)
        if not approval_url:
            raise PayPalError("PayPal did not return an approval link.")
    except PayPalError as e:
        update_contribution_status(contribution_id, "failed", result_desc=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    return {**_public_contribution(get_contribution(contribution_id)), "approval_url": approval_url}


@app.post(
    "/contributions/paypal/capture",
    summary="Public: capture a PayPal contribution after the contributor approves it on PayPal",
    tags=["Membership"],
)
def api_capture_paypal_contribution(body: PayPalOrderRefIn):
    contribution = get_contribution_by_paypal_order_id(body.order_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="Contribution not found.")
    try:
        capture_order(body.order_id)
        update_contribution_status(contribution["id"], "completed")
    except PayPalError as e:
        update_contribution_status(contribution["id"], "failed", result_desc=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    return _public_contribution(get_contribution(contribution["id"]))


@app.post(
    "/contributions/paypal/cancel",
    summary="Public: mark a PayPal contribution cancelled after the contributor cancels on PayPal",
    tags=["Membership"],
)
def api_cancel_paypal_contribution(body: PayPalOrderRefIn):
    contribution = get_contribution_by_paypal_order_id(body.order_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="Contribution not found.")
    update_contribution_status(contribution["id"], "cancelled", result_desc="Cancelled by contributor.")
    return _public_contribution(get_contribution(contribution["id"]))


@app.get(
    "/contributions/summary",
    summary="Public: total campaign funds raised per currency (completed contributions only)",
    tags=["Membership"],
)
def api_contributions_summary():
    return sum_completed_contributions()


@app.get(
    "/contributions/public-list",
    summary="Public: transparency list of completed contributions (no phone/email)",
    tags=["Membership"],
)
def api_public_contributions_list(limit: int = 100, offset: int = 0):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    rows = list_contributions(status="completed", limit=limit, offset=offset)
    return [
        {
            "id": c["id"],
            "contributor_name": c["contributor_name"],
            "amount": float(c["amount"]),
            "currency": c["currency"],
            "payment_method": c["payment_method"],
            "created_at": c["created_at"].isoformat() if c.get("created_at") else None,
        }
        for c in rows
    ]


@app.post(
    "/contributions/mpesa/callback",
    summary="Public: Safaricom Daraja STK push result callback (configured as MPESA_CALLBACK_URL)",
    tags=["Membership"],
)
async def mpesa_callback(request: Request):
    payload = await request.json()
    callback = ((payload or {}).get("Body") or {}).get("stkCallback") or {}
    checkout_request_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    result_desc = callback.get("ResultDesc", "")

    contribution = (
        get_contribution_by_checkout_request_id(checkout_request_id) if checkout_request_id else None
    )
    if contribution:
        if str(result_code) == "0":
            items = {
                i.get("Name"): i.get("Value")
                for i in (callback.get("CallbackMetadata") or {}).get("Item", [])
            }
            update_contribution_status(
                contribution["id"], "completed",
                mpesa_receipt_number=str(items.get("MpesaReceiptNumber", "")),
                result_desc=result_desc,
            )
        else:
            update_contribution_status(contribution["id"], "failed", result_desc=result_desc)

    # Daraja requires this exact envelope in the response regardless of outcome,
    # or it will keep retrying the callback.
    return {"ResultCode": 0, "ResultDesc": "Success"}


# ═══════════════════════════════════════════════════════════════════════════
# 🎯 Campaign Mgt — campaign team roster/groups, materials, routes
# ═══════════════════════════════════════════════════════════════════════════

_CAMPAIGN_TEAM_TYPE = "campaign"


class TeamRosterIn(BaseModel):
    username: str
    position: str
    password: str | None = None  # only used when creating a brand-new account
    other_names: str = ""
    surname: str = ""
    email: str = ""
    id_passport_number: str = ""
    phone_number: str = ""
    gender: str = ""
    date_of_birth: date | None = None
    county: str = ""
    sub_county: str = ""
    ward: str = ""
    ward_id: str | None = None


class TeamGroupIn(BaseModel):
    name: str
    description: str = ""


class TeamMemberIn(BaseModel):
    username: str


class MaterialIn(BaseModel):
    name: str
    unit: str = ""
    quantity: int = 0
    description: str = ""


class MaterialAssignIn(BaseModel):
    material_id: int
    quantity: int


class CampaignLocationIn(BaseModel):
    name: str
    campaign: str = ""
    description: str = ""
    address: str = ""
    county: str = ""
    county_code: str = ""
    constituency: str = ""
    constituency_code: str = ""
    ward: str = ""
    ward_code: str = ""
    ward_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str = "Planned"
    notes: str = ""
    date_from: date | None = None
    date_to: date | None = None


@app.get("/campaign-team/roster", summary="List/search the campaign team roster", tags=["Campaign Mgt"])
def api_list_campaign_roster(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_users_by_team_type(_CAMPAIGN_TEAM_TYPE, search),
        "items": list_users_by_team_type(_CAMPAIGN_TEAM_TYPE, search, limit=limit, offset=offset),
    }


@app.post("/campaign-team/roster", summary="Add a member to the campaign team — creates or links an account (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_roster_member(body: TeamRosterIn, current_user: dict = Depends(require_admin)):
    role_map = {p["title"]: p["role"] for p in list_positions(team_type=_CAMPAIGN_TEAM_TYPE)}
    if body.position not in role_map:
        raise HTTPException(status_code=400, detail=f"Unknown campaign position '{body.position}'.")
    if get_user(body.username):
        assign_user_to_team(body.username, _CAMPAIGN_TEAM_TYPE, body.position)
    else:
        if not body.password:
            raise HTTPException(status_code=400, detail="password is required to create a new account.")
        try:
            create_user(
                username=body.username, password=body.password, role=role_map[body.position],
                other_names=body.other_names, surname=body.surname, email=body.email,
                position=body.position, id_passport_number=body.id_passport_number,
                phone_number=body.phone_number, gender=body.gender, date_of_birth=body.date_of_birth,
                county=body.county, sub_county=body.sub_county, ward=body.ward, ward_id=body.ward_id,
            )
        except Exception as e:
            raise _duplicate_or_bad_request(e)
        assign_user_to_team(body.username, _CAMPAIGN_TEAM_TYPE, body.position)
    return _public_user(get_user(body.username))


@app.put("/campaign-team/roster/{username}", summary="Update a campaign team roster member (admin only)", tags=["Campaign Mgt"])
def api_update_campaign_roster_member(
    username: str, body: TeamRosterIn, current_user: dict = Depends(require_admin),
):
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        update_user_profile(
            username, other_names=body.other_names, surname=body.surname, email=body.email,
            position=body.position, id_passport_number=body.id_passport_number,
            phone_number=body.phone_number, gender=body.gender, date_of_birth=body.date_of_birth,
            county=body.county, sub_county=body.sub_county, ward=body.ward, ward_id=body.ward_id,
        )
        assign_user_to_team(username, _CAMPAIGN_TEAM_TYPE, body.position)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _public_user(get_user(username))


@app.delete("/campaign-team/roster/{username}", summary="Remove a member from the campaign team (admin only)", tags=["Campaign Mgt"])
def api_remove_campaign_roster_member(
    username: str,
    delete_account: bool = Query(False, description="Also delete the underlying user account entirely"),
    current_user: dict = Depends(require_admin),
):
    remove_user_from_team(username, _CAMPAIGN_TEAM_TYPE)
    if delete_account:
        delete_user(username)
    return {"username": username, "removed_from_team": True, "account_deleted": delete_account}


@app.get("/campaign-team/groups", summary="List/search campaign teams (roster sub-groups)", tags=["Campaign Mgt"])
def api_list_campaign_groups(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return list_campaign_teams(search)


@app.get("/campaign-team/groups/{id}", summary="Get a single campaign team", tags=["Campaign Mgt"])
def api_get_campaign_group(id: str, current_user: dict = Depends(get_current_user)):
    team = get_campaign_team(id)
    if not team:
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    return team


@app.post("/campaign-team/groups", summary="Create a campaign team (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_group(body: TeamGroupIn, current_user: dict = Depends(require_admin)):
    try:
        new_id = add_campaign_team(body.name, body.description)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_campaign_team(str(new_id))


@app.put("/campaign-team/groups/{id}", summary="Update a campaign team (admin only)", tags=["Campaign Mgt"])
def api_update_campaign_group(id: str, body: TeamGroupIn, current_user: dict = Depends(require_admin)):
    if not get_campaign_team(id):
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    try:
        update_campaign_team(id, body.name, body.description)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_campaign_team(id)


@app.delete("/campaign-team/groups/{id}", summary="Delete a campaign team (admin only)", tags=["Campaign Mgt"])
def api_delete_campaign_group(id: str, current_user: dict = Depends(require_admin)):
    delete_campaign_team(id)
    return {"deleted": id}


@app.get("/campaign-team/groups/{id}/members", summary="List a campaign team's members", tags=["Campaign Mgt"])
def api_list_campaign_group_members(id: str, current_user: dict = Depends(get_current_user)):
    if not get_campaign_team(id):
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    return list_campaign_team_members(id)


@app.post("/campaign-team/groups/{id}/members", summary="Add a member to a campaign team (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_group_member(id: str, body: TeamMemberIn, current_user: dict = Depends(require_admin)):
    if not get_campaign_team(id):
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    add_campaign_team_member(id, body.username)
    return list_campaign_team_members(id)


@app.delete("/campaign-team/groups/{id}/members/{username}", summary="Remove a member from a campaign team (admin only)", tags=["Campaign Mgt"])
def api_remove_campaign_group_member(id: str, username: str, current_user: dict = Depends(require_admin)):
    remove_campaign_team_member(id, username)
    return {"team_id": id, "removed_username": username}


@app.get("/campaign-materials", summary="List/search campaign materials", tags=["Campaign Mgt"])
def api_list_campaign_materials(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return list_materials(search, material_type=_CAMPAIGN_TEAM_TYPE)


@app.get("/campaign-materials/{id}", summary="Get a single campaign material", tags=["Campaign Mgt"])
def api_get_campaign_material(id: str, current_user: dict = Depends(get_current_user)):
    material = get_material(id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found.")
    return material


@app.post("/campaign-materials", summary="Create a campaign material (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_material(body: MaterialIn, current_user: dict = Depends(require_admin)):
    try:
        new_id = add_material(body.name, body.unit, body.quantity, body.description, _CAMPAIGN_TEAM_TYPE)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_material(str(new_id))


@app.put("/campaign-materials/{id}", summary="Update a campaign material (admin only)", tags=["Campaign Mgt"])
def api_update_campaign_material(id: str, body: MaterialIn, current_user: dict = Depends(require_admin)):
    if not get_material(id):
        raise HTTPException(status_code=404, detail="Material not found.")
    try:
        update_material(id, body.name, body.unit, body.quantity, body.description, _CAMPAIGN_TEAM_TYPE)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_material(id)


@app.delete("/campaign-materials/{id}", summary="Delete a campaign material (admin only)", tags=["Campaign Mgt"])
def api_delete_campaign_material(id: str, current_user: dict = Depends(require_admin)):
    delete_material(id)
    return {"deleted": id}


@app.get("/campaign-materials/{id}/assignments", summary="List which campaign teams a material is assigned to", tags=["Campaign Mgt"])
def api_campaign_material_assignments(id: str, current_user: dict = Depends(get_current_user)):
    if not get_material(id):
        raise HTTPException(status_code=404, detail="Material not found.")
    return {"assigned_quantity": assigned_material_quantity(id), "assignments": list_material_assignments(id)}


@app.get("/campaign-team/groups/{id}/materials", summary="List materials assigned to a campaign team", tags=["Campaign Mgt"])
def api_list_campaign_group_materials(id: str, current_user: dict = Depends(get_current_user)):
    if not get_campaign_team(id):
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    return list_team_material_assignments(id)


@app.post("/campaign-team/groups/{id}/materials", summary="Assign a material to a campaign team (admin only)", tags=["Campaign Mgt"])
def api_assign_campaign_group_material(id: str, body: MaterialAssignIn, current_user: dict = Depends(require_admin)):
    if not get_campaign_team(id):
        raise HTTPException(status_code=404, detail="Campaign team not found.")
    assign_material_to_team(body.material_id, id, body.quantity)
    return list_team_material_assignments(id)


@app.delete(
    "/campaign-team/groups/{id}/materials/{material_id}",
    summary="Unassign a material from a campaign team (admin only)", tags=["Campaign Mgt"],
)
def api_remove_campaign_group_material(id: str, material_id: str, current_user: dict = Depends(require_admin)):
    remove_material_assignment(material_id, id)
    return {"team_id": id, "material_id": material_id}


@app.get(
    "/campaign-routes",
    summary="List/search campaign routes (locations) — anonymous callers only ever see published ones",
    tags=["Campaign Mgt"],
)
def api_list_campaign_routes(
    search: str = Query(""),
    published: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict | None = Depends(get_optional_user),
):
    if current_user is None:
        published = True  # anonymous callers never see drafts, regardless of what they asked for
    return {
        "total": count_campaign_locations(search, published),
        "items": list_campaign_locations(search, published, limit=limit, offset=offset),
    }


@app.get(
    "/campaign-routes/status-counts", summary="Published/draft counts (admin only)", tags=["Campaign Mgt"],
)
def api_campaign_routes_status_counts(search: str = Query(""), current_user: dict = Depends(require_admin)):
    return count_campaign_locations_by_publish_state(search)


@app.get(
    "/campaign-routes/{id}",
    summary="Get a single campaign route/location — anonymous callers can only see published ones",
    tags=["Campaign Mgt"],
)
def api_get_campaign_route(id: str, current_user: dict | None = Depends(get_optional_user)):
    location = get_campaign_location(id)
    if not location:
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    if current_user is None and not location.get("published"):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    return location


@app.post("/campaign-routes", summary="Create a campaign route/location (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_route(body: CampaignLocationIn, current_user: dict = Depends(require_admin)):
    if body.status not in CAMPAIGN_LOCATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {CAMPAIGN_LOCATION_STATUSES}")
    try:
        new_id = add_campaign_location(**body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_campaign_location(str(new_id))


@app.put("/campaign-routes/{id}", summary="Update a campaign route/location (admin only)", tags=["Campaign Mgt"])
def api_update_campaign_route(id: str, body: CampaignLocationIn, current_user: dict = Depends(require_admin)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    if body.status not in CAMPAIGN_LOCATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {CAMPAIGN_LOCATION_STATUSES}")
    try:
        update_campaign_location(id, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_campaign_location(id)


@app.delete("/campaign-routes/{id}", summary="Delete a campaign route/location (admin only)", tags=["Campaign Mgt"])
def api_delete_campaign_route(id: str, current_user: dict = Depends(require_admin)):
    delete_campaign_location(id)
    return {"deleted": id}


@app.put("/campaign-routes/{id}/publish", summary="Publish/unpublish a campaign route (admin only)", tags=["Campaign Mgt"])
def api_publish_campaign_route(id: str, published: bool = Query(...), current_user: dict = Depends(require_admin)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    set_campaign_location_published(id, published)
    return get_campaign_location(id)


@app.put("/campaign-routes/{id}/complete", summary="Mark a campaign route as completed (admin only)", tags=["Campaign Mgt"])
def api_complete_campaign_route(id: str, current_user: dict = Depends(require_admin)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    set_campaign_location_status(id, "Completed")
    return get_campaign_location(id)


@app.get("/campaign-routes/{id}/team", summary="List a campaign route's assigned team members", tags=["Campaign Mgt"])
def api_list_campaign_route_team(id: str, current_user: dict = Depends(get_current_user)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    return list_location_team_members(id)


@app.post("/campaign-routes/{id}/team", summary="Assign a team member to a campaign route (admin only)", tags=["Campaign Mgt"])
def api_add_campaign_route_team_member(id: str, body: TeamMemberIn, current_user: dict = Depends(require_admin)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    add_location_team_member(id, body.username)
    return list_location_team_members(id)


@app.delete("/campaign-routes/{id}/team/{username}", summary="Unassign a team member from a campaign route (admin only)", tags=["Campaign Mgt"])
def api_remove_campaign_route_team_member(id: str, username: str, current_user: dict = Depends(require_admin)):
    remove_location_team_member(id, username)
    return {"location_id": id, "removed_username": username}


@app.post("/campaign-routes/{id}/banner", summary="Upload/replace a campaign route's banner photo (admin only)", tags=["Campaign Mgt"])
async def api_upload_campaign_route_banner(
    id: str, file: UploadFile = File(...), current_user: dict = Depends(require_admin),
):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    contents = await file.read()
    _validate_campaign_image(file.filename, contents)
    set_campaign_location_banner(id, file.filename, contents)
    return get_campaign_location(id)


@app.delete("/campaign-routes/{id}/banner", summary="Remove a campaign route's banner photo (admin only)", tags=["Campaign Mgt"])
def api_delete_campaign_route_banner(id: str, current_user: dict = Depends(require_admin)):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    remove_campaign_location_banner(id)
    return get_campaign_location(id)


@app.get(
    "/campaign-routes/{id}/banner",
    summary="Public: fetch a campaign route's banner image (only if published)",
    tags=["Campaign Mgt"],
)
def api_get_campaign_route_banner(id: str, current_user: dict | None = Depends(get_optional_user)):
    location = get_campaign_location(id)
    if not location:
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    if current_user is None and not location.get("published"):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    result = get_campaign_location_banner_bytes(id)
    if not result:
        raise HTTPException(status_code=404, detail="This campaign route has no banner image.")
    file_bytes, stored_name = result
    media_type = mimetypes.guess_type(stored_name)[0] or "application/octet-stream"
    return Response(
        content=file_bytes, media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{stored_name}"'},
    )


def _campaign_route_media_publicly_visible(location: dict) -> bool:
    return bool(location.get("published")) and location.get("status") == "Completed"


@app.get(
    "/campaign-routes/{id}/media",
    summary="List a campaign route's media gallery — anonymous callers only see it once published and completed",
    tags=["Campaign Mgt"],
)
def api_list_campaign_route_media(id: str, current_user: dict | None = Depends(get_optional_user)):
    location = get_campaign_location(id)
    if not location:
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    if current_user is None and not _campaign_route_media_publicly_visible(location):
        return {"items": []}
    return {"items": list_campaign_location_media(id)}


@app.post("/campaign-routes/{id}/media", summary="Upload media photos to a campaign route's gallery (admin only)", tags=["Campaign Mgt"])
async def api_upload_campaign_route_media(
    id: str, files: list[UploadFile] = File(...), current_user: dict = Depends(require_admin),
):
    if not get_campaign_location(id):
        raise HTTPException(status_code=404, detail="Campaign route not found.")
    uploaded = []
    for f in files:
        contents = await f.read()
        _validate_campaign_image(f.filename, contents)
        stored_name = save_campaign_media_file(id, f.filename, contents)
        media_id = add_campaign_location_media(id, stored_name, f.filename, current_user["sub"])
        uploaded.append(media_id)
    return {"items": list_campaign_location_media(id), "uploaded": uploaded}


@app.get(
    "/campaign-location-media/{media_id}",
    summary="Public: fetch one campaign route media photo (only if the route is published and completed)",
    tags=["Campaign Mgt"],
)
def api_get_campaign_location_media(media_id: int, current_user: dict | None = Depends(get_optional_user)):
    media = get_campaign_location_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found.")
    location = get_campaign_location(media["location_id"])
    if current_user is None and (not location or not _campaign_route_media_publicly_visible(location)):
        raise HTTPException(status_code=404, detail="Media not found.")
    result = get_campaign_location_media_bytes(media_id)
    if not result:
        raise HTTPException(status_code=404, detail="Media file is missing on disk.")
    file_bytes, display_name = result
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return Response(
        content=file_bytes, media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{display_name}"'},
    )


@app.delete("/campaign-location-media/{media_id}", summary="Delete a campaign route media photo (admin only)", tags=["Campaign Mgt"])
def api_delete_campaign_location_media(media_id: int, current_user: dict = Depends(require_admin)):
    if not get_campaign_location_media(media_id):
        raise HTTPException(status_code=404, detail="Media not found.")
    delete_campaign_location_media(media_id)
    return {"deleted": media_id}


# ── Opinion Polls — pollster-reported standings per office, with a per-
# candidate/party breakdown (mirrors the vote-tally shape so the outward-
# facing site can render both with the same kind of bar chart) ──────────────

class OpinionPollResultIn(BaseModel):
    id: int | None = None  # existing result row id, when editing — preserves vote_count
    candidate_id: int | None = None
    candidate_name: str
    party_id: int | None = None
    percentage: float = Field(0, ge=0, le=100)  # ignored for source='self_hosted' (computed from votes)


class OpinionPollIn(BaseModel):
    title: str
    position: str = ""
    pollster: str = ""
    sample_size: int | None = None
    margin_of_error: float | None = None
    date_conducted: date | None = None
    methodology: str = ""
    source_url: str = ""
    notes: str = ""
    source: str = "pollster"  # 'pollster' (admin-entered %) or 'self_hosted' (public voting)
    results: list[OpinionPollResultIn] = []


class OpinionPollVoteIn(BaseModel):
    result_id: int


def _opinion_poll_with_results(poll: dict) -> dict:
    return {**poll, "results": list_opinion_poll_results(poll["id"])}


def _hash_voter(request: Request, poll_id: str) -> str:
    """Salted hash of the caller's IP, scoped to this poll — lets the DB
    enforce one vote per (poll, IP) without ever storing the raw IP."""
    ip = _client_ip(request)
    return hashlib.sha256(f"{SECRET_KEY}:{poll_id}:{ip}".encode()).hexdigest()


@app.get(
    "/opinion-polls",
    summary="List/search opinion polls — anonymous callers only ever see published ones",
    tags=["Campaign Mgt"],
)
def api_list_opinion_polls(
    search: str = Query(""),
    position: str | None = Query(None),
    published: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict | None = Depends(get_optional_user),
):
    if current_user is None:
        published = True  # anonymous callers never see drafts, regardless of what they asked for
    return {
        "total": count_opinion_polls(search, position, published),
        "items": list_opinion_polls(search, position, published, limit=limit, offset=offset),
    }


@app.get(
    "/opinion-polls/status-counts", summary="Published/draft counts (admin only)", tags=["Campaign Mgt"],
)
def api_opinion_polls_status_counts(search: str = Query(""), current_user: dict = Depends(require_admin)):
    return count_opinion_polls_by_publish_state(search)


@app.get(
    "/opinion-polls/{id}",
    summary="Get a single opinion poll with its candidate breakdown — anonymous callers can only see published ones",
    tags=["Campaign Mgt"],
)
def api_get_opinion_poll(id: str, current_user: dict | None = Depends(get_optional_user)):
    poll = get_opinion_poll(id)
    if not poll:
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    if current_user is None and not poll.get("published"):
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    return _opinion_poll_with_results(poll)


def _check_opinion_poll_source(source: str) -> None:
    if source not in OPINION_POLL_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source '{source}'. Valid: {OPINION_POLL_SOURCES}",
        )


@app.post("/opinion-polls", summary="Create an opinion poll (admin only)", tags=["Campaign Mgt"])
def api_create_opinion_poll(body: OpinionPollIn, current_user: dict = Depends(require_admin)):
    _check_opinion_poll_source(body.source)
    payload = body.model_dump()
    results = payload.pop("results")
    try:
        new_id = create_opinion_poll(**payload, results=results)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _opinion_poll_with_results(get_opinion_poll(str(new_id)))


@app.put("/opinion-polls/{id}", summary="Update an opinion poll (admin only)", tags=["Campaign Mgt"])
def api_update_opinion_poll(id: str, body: OpinionPollIn, current_user: dict = Depends(require_admin)):
    if not get_opinion_poll(id):
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    _check_opinion_poll_source(body.source)
    payload = body.model_dump()
    results = payload.pop("results")
    try:
        update_opinion_poll(id, **payload, results=results)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _opinion_poll_with_results(get_opinion_poll(id))


@app.delete("/opinion-polls/{id}", summary="Delete an opinion poll (admin only)", tags=["Campaign Mgt"])
def api_delete_opinion_poll(id: str, current_user: dict = Depends(require_admin)):
    if not get_opinion_poll(id):
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    delete_opinion_poll(id)
    return {"deleted": id}


@app.put(
    "/opinion-polls/{id}/publish", summary="Publish/unpublish an opinion poll (admin only)", tags=["Campaign Mgt"],
)
def api_publish_opinion_poll(id: str, published: bool = Query(...), current_user: dict = Depends(require_admin)):
    if not get_opinion_poll(id):
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    set_opinion_poll_published(id, published)
    return _opinion_poll_with_results(get_opinion_poll(id))


@app.post(
    "/opinion-polls/{id}/vote",
    summary="Public: cast a vote in a self-hosted opinion poll (one vote per IP, rate-limited)",
    tags=["Campaign Mgt"],
)
def api_vote_opinion_poll(
    id: str, body: OpinionPollVoteIn, request: Request,
    _rl: None = Depends(rate_limit("opinion_poll_vote", max_requests=10, window_seconds=3600)),
):
    poll = get_opinion_poll(id)
    if not poll or not poll.get("published"):
        raise HTTPException(status_code=404, detail="Opinion poll not found.")
    if poll.get("source") != "self_hosted":
        raise HTTPException(status_code=400, detail="This poll does not accept public votes.")
    try:
        cast_opinion_poll_vote(id, body.result_id, _hash_voter(request, id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid option for this poll.")
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=409, detail="You've already voted in this poll.")
        raise _duplicate_or_bad_request(e)
    return _opinion_poll_with_results(get_opinion_poll(id))


# ═══════════════════════════════════════════════════════════════════════════
# 📰 Feed — public, read-only view of the org activity feed. Posting,
# commenting, and liking remain internal-only (Streamlit talks to db.py
# directly for those); these endpoints only ever read.
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/feed/posts", summary="Public: list recent feed posts (read-only)", tags=["Feed"])
def api_list_feed_posts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {
        "total": count_feed_posts(),
        "items": list_feed_posts(limit=limit, offset=offset),
    }


@app.get(
    "/feed/posts/{post_id}/comments",
    summary="Public: list comments on a feed post (read-only)",
    tags=["Feed"],
)
def api_list_feed_post_comments(post_id: int):
    return list_feed_post_comments(post_id)


@app.get("/feed/images/{image_id}", summary="Public: fetch a feed post image", tags=["Feed"])
def api_get_feed_image(image_id: int):
    result = get_feed_post_image_bytes(image_id)
    if not result:
        raise HTTPException(status_code=404, detail="Image not found.")
    file_bytes, display_name = result
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return Response(
        content=file_bytes, media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{display_name}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════
# 🗳️ Election Mgt — election team roster/groups, materials, form upload
# ═══════════════════════════════════════════════════════════════════════════

_ELECTION_TEAM_TYPE = "election"


@app.get("/election-team/roster", summary="List/search the election team roster", tags=["Election Mgt"])
def api_list_election_roster(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    return {
        "total": count_users_by_team_type(_ELECTION_TEAM_TYPE, search),
        "items": list_users_by_team_type(_ELECTION_TEAM_TYPE, search, limit=limit, offset=offset),
    }


@app.post("/election-team/roster", summary="Add a member to the election team — creates or links an account (admin only)", tags=["Election Mgt"])
def api_add_election_roster_member(body: TeamRosterIn, current_user: dict = Depends(require_admin)):
    role_map = {p["title"]: p["role"] for p in list_positions(team_type=_ELECTION_TEAM_TYPE)}
    if body.position not in role_map:
        raise HTTPException(status_code=400, detail=f"Unknown election position '{body.position}'.")
    if get_user(body.username):
        assign_user_to_team(body.username, _ELECTION_TEAM_TYPE, body.position)
    else:
        if not body.password:
            raise HTTPException(status_code=400, detail="password is required to create a new account.")
        try:
            create_user(
                username=body.username, password=body.password, role=role_map[body.position],
                other_names=body.other_names, surname=body.surname, email=body.email,
                position=body.position, id_passport_number=body.id_passport_number,
                phone_number=body.phone_number, gender=body.gender, date_of_birth=body.date_of_birth,
                county=body.county, sub_county=body.sub_county, ward=body.ward, ward_id=body.ward_id,
            )
        except Exception as e:
            raise _duplicate_or_bad_request(e)
        assign_user_to_team(body.username, _ELECTION_TEAM_TYPE, body.position)
    return _public_user(get_user(body.username))


@app.put("/election-team/roster/{username}", summary="Update an election team roster member (admin only)", tags=["Election Mgt"])
def api_update_election_roster_member(
    username: str, body: TeamRosterIn, current_user: dict = Depends(require_admin),
):
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        update_user_profile(
            username, other_names=body.other_names, surname=body.surname, email=body.email,
            position=body.position, id_passport_number=body.id_passport_number,
            phone_number=body.phone_number, gender=body.gender, date_of_birth=body.date_of_birth,
            county=body.county, sub_county=body.sub_county, ward=body.ward, ward_id=body.ward_id,
        )
        assign_user_to_team(username, _ELECTION_TEAM_TYPE, body.position)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _public_user(get_user(username))


@app.delete("/election-team/roster/{username}", summary="Remove a member from the election team (admin only)", tags=["Election Mgt"])
def api_remove_election_roster_member(
    username: str,
    delete_account: bool = Query(False, description="Also delete the underlying user account entirely"),
    current_user: dict = Depends(require_admin),
):
    remove_user_from_team(username, _ELECTION_TEAM_TYPE)
    if delete_account:
        delete_user(username)
    return {"username": username, "removed_from_team": True, "account_deleted": delete_account}


@app.get("/election-team/groups", summary="List/search election teams (roster sub-groups)", tags=["Election Mgt"])
def api_list_election_groups(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return list_election_teams(search)


@app.get("/election-team/groups/{id}", summary="Get a single election team", tags=["Election Mgt"])
def api_get_election_group(id: str, current_user: dict = Depends(get_current_user)):
    team = get_election_team(id)
    if not team:
        raise HTTPException(status_code=404, detail="Election team not found.")
    return team


@app.post("/election-team/groups", summary="Create an election team (admin only)", tags=["Election Mgt"])
def api_add_election_group(body: TeamGroupIn, current_user: dict = Depends(require_admin)):
    try:
        new_id = add_election_team(body.name, body.description)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_election_team(str(new_id))


@app.put("/election-team/groups/{id}", summary="Update an election team (admin only)", tags=["Election Mgt"])
def api_update_election_group(id: str, body: TeamGroupIn, current_user: dict = Depends(require_admin)):
    if not get_election_team(id):
        raise HTTPException(status_code=404, detail="Election team not found.")
    try:
        update_election_team(id, body.name, body.description)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_election_team(id)


@app.delete("/election-team/groups/{id}", summary="Delete an election team (admin only)", tags=["Election Mgt"])
def api_delete_election_group(id: str, current_user: dict = Depends(require_admin)):
    delete_election_team(id)
    return {"deleted": id}


@app.get("/election-team/groups/{id}/members", summary="List an election team's members", tags=["Election Mgt"])
def api_list_election_group_members(id: str, current_user: dict = Depends(get_current_user)):
    if not get_election_team(id):
        raise HTTPException(status_code=404, detail="Election team not found.")
    return list_election_team_members(id)


@app.post("/election-team/groups/{id}/members", summary="Add a member to an election team (admin only)", tags=["Election Mgt"])
def api_add_election_group_member(id: str, body: TeamMemberIn, current_user: dict = Depends(require_admin)):
    if not get_election_team(id):
        raise HTTPException(status_code=404, detail="Election team not found.")
    add_election_team_member(id, body.username)
    return list_election_team_members(id)


@app.delete("/election-team/groups/{id}/members/{username}", summary="Remove a member from an election team (admin only)", tags=["Election Mgt"])
def api_remove_election_group_member(id: str, username: str, current_user: dict = Depends(require_admin)):
    remove_election_team_member(id, username)
    return {"team_id": id, "removed_username": username}


@app.get("/election-materials", summary="List/search election materials", tags=["Election Mgt"])
def api_list_election_materials(search: str = Query(""), current_user: dict = Depends(get_current_user)):
    return list_materials(search, material_type=_ELECTION_TEAM_TYPE)


@app.get("/election-materials/{id}", summary="Get a single election material", tags=["Election Mgt"])
def api_get_election_material(id: str, current_user: dict = Depends(get_current_user)):
    material = get_material(id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found.")
    return material


@app.post("/election-materials", summary="Create an election material (admin only)", tags=["Election Mgt"])
def api_add_election_material(body: MaterialIn, current_user: dict = Depends(require_admin)):
    try:
        new_id = add_material(body.name, body.unit, body.quantity, body.description, _ELECTION_TEAM_TYPE)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_material(str(new_id))


@app.put("/election-materials/{id}", summary="Update an election material (admin only)", tags=["Election Mgt"])
def api_update_election_material(id: str, body: MaterialIn, current_user: dict = Depends(require_admin)):
    if not get_material(id):
        raise HTTPException(status_code=404, detail="Material not found.")
    try:
        update_material(id, body.name, body.unit, body.quantity, body.description, _ELECTION_TEAM_TYPE)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_material(id)


@app.delete("/election-materials/{id}", summary="Delete an election material (admin only)", tags=["Election Mgt"])
def api_delete_election_material(id: str, current_user: dict = Depends(require_admin)):
    delete_material(id)
    return {"deleted": id}


@app.get("/election-materials/{id}/assignments", summary="List which election teams a material is assigned to", tags=["Election Mgt"])
def api_election_material_assignments(id: str, current_user: dict = Depends(get_current_user)):
    if not get_material(id):
        raise HTTPException(status_code=404, detail="Material not found.")
    return {"assigned_quantity": assigned_material_quantity(id), "assignments": list_election_material_assignments(id)}


@app.get("/election-team/groups/{id}/materials", summary="List materials assigned to an election team", tags=["Election Mgt"])
def api_list_election_group_materials(id: str, current_user: dict = Depends(get_current_user)):
    if not get_election_team(id):
        raise HTTPException(status_code=404, detail="Election team not found.")
    return list_election_team_material_assignments(id)


@app.post("/election-team/groups/{id}/materials", summary="Assign a material to an election team (admin only)", tags=["Election Mgt"])
def api_assign_election_group_material(id: str, body: MaterialAssignIn, current_user: dict = Depends(require_admin)):
    if not get_election_team(id):
        raise HTTPException(status_code=404, detail="Election team not found.")
    assign_election_material_to_team(body.material_id, id, body.quantity)
    return list_election_team_material_assignments(id)


@app.delete(
    "/election-team/groups/{id}/materials/{material_id}",
    summary="Unassign a material from an election team (admin only)", tags=["Election Mgt"],
)
def api_remove_election_group_material(id: str, material_id: str, current_user: dict = Depends(require_admin)):
    remove_election_material_assignment(material_id, id)
    return {"team_id": id, "material_id": material_id}


# ── Upload & background processing (Election Mgt ➜ Upload Form) ─────────────

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


@app.post("/upload", summary="Upload a form (PDF/PNG/JPG/TIFF/BMP/WEBP) — saves to docs/forms/, parses with Claude, writes to DB", tags=["Election Mgt"])
async def upload_form(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-process even if already in DB"),
    current_user: dict = Depends(get_current_user),
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
        _jobs[job_id] = {
            "status": "pending",
            "filename": file.filename,
            "uploaded_by": current_user["sub"],
        }

    background_tasks.add_task(_run_job, job_id, pdf_path, api_key, force)
    return {"job_id": job_id, "status": "pending", "filename": file.filename, "uploaded_by": current_user["sub"]}


@app.get("/jobs/{job_id}", summary="Poll the status of an upload processing job", tags=["Election Mgt"])
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


# ═══════════════════════════════════════════════════════════════════════════
# 🗣️ Collaboration — chats, calls, events calendar, activities & tasks
# ═══════════════════════════════════════════════════════════════════════════

class ChatMessageIn(BaseModel):
    message: str


class ChatGroupIn(BaseModel):
    name: str
    member_usernames: list[str] = []


class ChatGroupMembersIn(BaseModel):
    usernames: list[str]


class CallCreateIn(BaseModel):
    callee_username: str
    offer_sdp: str


class CallAcceptIn(BaseModel):
    answer_sdp: str


class IceCandidateIn(BaseModel):
    candidate_json: str


class EventIn(BaseModel):
    event_type: str
    title: str
    description: str = ""
    start_date: date
    end_date: date
    member_usernames: list[str] = []
    start_time: str | None = None
    end_time: str | None = None
    whole_day: bool = False
    recurrence_freq: str = "none"
    recurrence_interval: int = 1
    recurrence_unit: str | None = None
    recurrence_days_of_week: str | None = None
    recurrence_until: date | None = None


class ActivityIn(BaseModel):
    title: str
    description: str = ""
    start_date: date
    end_date: date
    priority: str = "medium"


class TaskIn(BaseModel):
    title: str
    description: str = ""
    start_date: date
    end_date: date
    priority: str = "medium"
    assignee_usernames: list[str] = []


class TaskStatusIn(BaseModel):
    status: str


@app.get("/chats/conversations", summary="List your DM conversation peers", tags=["Collaboration"])
def api_list_dm_conversations(current_user: dict = Depends(get_current_user)):
    return list_dm_conversations(current_user["sub"])


@app.get("/chats/dm/{other_username}", summary="List your DM history with another user", tags=["Collaboration"])
def api_list_dm_messages(
    other_username: str, limit: int = Query(200, ge=1, le=1000), current_user: dict = Depends(get_current_user),
):
    return list_chat_messages(current_user["sub"], other_username, limit=limit)


@app.post("/chats/dm/{other_username}", summary="Send a direct message", tags=["Collaboration"])
def api_send_dm(other_username: str, body: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    msg_id = send_chat_message(current_user["sub"], other_username, body.message)
    return {"id": msg_id, "sender_username": current_user["sub"], "recipient_username": other_username}


@app.get("/chats/groups", summary="List the group chats you belong to", tags=["Collaboration"])
def api_list_my_chat_groups(current_user: dict = Depends(get_current_user)):
    return list_user_groups(current_user["sub"])


@app.post("/chats/groups", summary="Create a group chat", tags=["Collaboration"])
def api_create_chat_group(body: ChatGroupIn, current_user: dict = Depends(get_current_user)):
    try:
        group_id = create_chat_group(body.name, current_user["sub"], body.member_usernames)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return {"id": group_id, "name": body.name, "created_by": current_user["sub"]}


@app.get("/chats/groups/{group_id}/members", summary="List a group chat's members (must be a member)", tags=["Collaboration"])
def api_list_chat_group_members(group_id: int, current_user: dict = Depends(get_current_user)):
    _check_group_member(current_user, group_id)
    return list_group_members(group_id)


@app.post("/chats/groups/{group_id}/members", summary="Add members to a group chat (must be a member)", tags=["Collaboration"])
def api_add_chat_group_members(group_id: int, body: ChatGroupMembersIn, current_user: dict = Depends(get_current_user)):
    _check_group_member(current_user, group_id)
    try:
        add_chat_group_members(group_id, body.usernames)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return list_group_members(group_id)


@app.get("/chats/groups/{group_id}/messages", summary="List a group chat's messages (must be a member)", tags=["Collaboration"])
def api_list_chat_group_messages(
    group_id: int, limit: int = Query(200, ge=1, le=1000), current_user: dict = Depends(get_current_user),
):
    _check_group_member(current_user, group_id)
    return list_group_chat_messages(group_id, limit=limit)


@app.post("/chats/groups/{group_id}/messages", summary="Send a message to a group chat (must be a member)", tags=["Collaboration"])
def api_send_chat_group_message(group_id: int, body: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    _check_group_member(current_user, group_id)
    msg_id = send_group_chat_message(group_id, current_user["sub"], body.message)
    return {"id": msg_id, "group_id": group_id, "sender_username": current_user["sub"]}


@app.post("/calls", summary="Start a call — creates it in 'ringing' status with your SDP offer", tags=["Collaboration"])
def api_create_call(body: CallCreateIn, current_user: dict = Depends(get_current_user)):
    call_id = create_call(current_user["sub"], body.callee_username, body.offer_sdp)
    return get_call(call_id)


@app.get("/calls/incoming", summary="Get your incoming (ringing) call, if any", tags=["Collaboration"])
def api_get_incoming_call(current_user: dict = Depends(get_current_user)):
    call = get_incoming_call(current_user["sub"])
    if not call:
        raise HTTPException(status_code=404, detail="No incoming call.")
    return call


@app.get("/calls/active", summary="Get your currently active call, if any", tags=["Collaboration"])
def api_get_active_call(current_user: dict = Depends(get_current_user)):
    call = get_active_call_for_user(current_user["sub"])
    if not call:
        raise HTTPException(status_code=404, detail="No active call.")
    return call


@app.get("/calls/{call_id}", summary="Get a call's status (must be a participant)", tags=["Collaboration"])
def api_get_call(call_id: int, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    return call


@app.post("/calls/{call_id}/accept", summary="Accept a call with your SDP answer (must be the callee)", tags=["Collaboration"])
def api_accept_call(call_id: int, body: CallAcceptIn, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    accept_call(call_id, body.answer_sdp)
    return get_call(call_id)


@app.post("/calls/{call_id}/decline", summary="Decline a call (must be a participant)", tags=["Collaboration"])
def api_decline_call(call_id: int, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    decline_call(call_id)
    return get_call(call_id)


@app.post("/calls/{call_id}/end", summary="End an active call (must be a participant)", tags=["Collaboration"])
def api_end_call(call_id: int, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    end_call(call_id)
    return get_call(call_id)


@app.post("/calls/{call_id}/missed", summary="Mark a call as missed (must be a participant)", tags=["Collaboration"])
def api_mark_call_missed(call_id: int, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    mark_call_missed(call_id)
    return get_call(call_id)


@app.post("/calls/{call_id}/ice-candidates", summary="Submit an ICE candidate for a call (must be a participant)", tags=["Collaboration"])
def api_add_ice_candidate(call_id: int, body: IceCandidateIn, current_user: dict = Depends(get_current_user)):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    candidate_id = add_ice_candidate(call_id, current_user["sub"], body.candidate_json)
    return {"id": candidate_id, "call_id": call_id}


@app.get(
    "/calls/{call_id}/ice-candidates",
    summary="Poll the other participant's ICE candidates for a call (must be a participant)", tags=["Collaboration"],
)
def api_list_ice_candidates(
    call_id: int, since_id: int = Query(0), current_user: dict = Depends(get_current_user),
):
    call = get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found.")
    _check_call_participant(current_user, call)
    return list_ice_candidates(call_id, current_user["sub"], since_id=since_id)


@app.get("/events", summary="List your events for a given month", tags=["Collaboration"])
def api_list_events(
    year: int = Query(...), month: int = Query(..., ge=1, le=12), current_user: dict = Depends(get_current_user),
):
    return list_events_for_user(current_user["sub"], year, month)


@app.post("/events", summary="Create an event", tags=["Collaboration"])
def api_create_event(body: EventIn, current_user: dict = Depends(get_current_user)):
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid event_type. Valid: {EVENT_TYPES}")
    if body.recurrence_freq not in RECURRENCE_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"Invalid recurrence_freq. Valid: {RECURRENCE_FREQUENCIES}")
    if body.recurrence_unit is not None and body.recurrence_unit not in RECURRENCE_UNITS:
        raise HTTPException(status_code=400, detail=f"Invalid recurrence_unit. Valid: {RECURRENCE_UNITS}")
    try:
        event_id = create_event(
            body.event_type, body.title, body.description, body.start_date, body.end_date, current_user["sub"],
            member_usernames=body.member_usernames, start_time=body.start_time, end_time=body.end_time,
            whole_day=body.whole_day, recurrence_freq=body.recurrence_freq, recurrence_interval=body.recurrence_interval,
            recurrence_unit=body.recurrence_unit, recurrence_days_of_week=body.recurrence_days_of_week,
            recurrence_until=body.recurrence_until,
        )
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_event(event_id)


@app.get("/events/{event_id}", summary="Get a single event (creator, member, or admin)", tags=["Collaboration"])
def api_get_event(event_id: int, current_user: dict = Depends(get_current_user)):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    members = {m["username"] for m in list_event_members(event_id)}
    if current_user["sub"] not in members:
        _check_event_owner_or_admin(current_user, event)
    return event


@app.put("/events/{event_id}", summary="Update an event (creator or admin)", tags=["Collaboration"])
def api_update_event(event_id: int, body: EventIn, current_user: dict = Depends(get_current_user)):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    _check_event_owner_or_admin(current_user, event)
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid event_type. Valid: {EVENT_TYPES}")
    if body.recurrence_freq not in RECURRENCE_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"Invalid recurrence_freq. Valid: {RECURRENCE_FREQUENCIES}")
    if body.recurrence_unit is not None and body.recurrence_unit not in RECURRENCE_UNITS:
        raise HTTPException(status_code=400, detail=f"Invalid recurrence_unit. Valid: {RECURRENCE_UNITS}")
    try:
        update_event(
            event_id, body.event_type, body.title, body.description, body.start_date, body.end_date,
            member_usernames=body.member_usernames, start_time=body.start_time, end_time=body.end_time,
            whole_day=body.whole_day, recurrence_freq=body.recurrence_freq, recurrence_interval=body.recurrence_interval,
            recurrence_unit=body.recurrence_unit, recurrence_days_of_week=body.recurrence_days_of_week,
            recurrence_until=body.recurrence_until,
        )
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_event(event_id)


@app.delete("/events/{event_id}", summary="Delete an event (creator or admin)", tags=["Collaboration"])
def api_delete_event(event_id: int, current_user: dict = Depends(get_current_user)):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    _check_event_owner_or_admin(current_user, event)
    delete_event(event_id)
    return {"deleted": event_id}


@app.get("/events/{event_id}/members", summary="List an event's members", tags=["Collaboration"])
def api_list_event_members(event_id: int, current_user: dict = Depends(get_current_user)):
    if not get_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found.")
    return list_event_members(event_id)


@app.post("/events/{event_id}/members", summary="Add a member to an event (creator or admin)", tags=["Collaboration"])
def api_add_event_member(event_id: int, body: TeamMemberIn, current_user: dict = Depends(get_current_user)):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    _check_event_owner_or_admin(current_user, event)
    add_event_member(event_id, body.username)
    return list_event_members(event_id)


@app.delete("/events/{event_id}/members/{username}", summary="Remove a member from an event (creator or admin)", tags=["Collaboration"])
def api_remove_event_member(event_id: int, username: str, current_user: dict = Depends(get_current_user)):
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    _check_event_owner_or_admin(current_user, event)
    remove_event_member(event_id, username)
    return {"event_id": event_id, "removed_username": username}


@app.get("/activities", summary="List activities (your own, or all if admin)", tags=["Collaboration"])
def api_list_activities(current_user: dict = Depends(get_current_user)):
    return list_activities_for_user(current_user["sub"], is_admin=current_user.get("role") == "admin")


@app.post("/activities", summary="Create an activity", tags=["Collaboration"])
def api_create_activity(body: ActivityIn, current_user: dict = Depends(get_current_user)):
    if body.priority not in ACTIVITY_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Valid: {ACTIVITY_PRIORITIES}")
    activity_id = create_activity(
        body.title, body.description, body.start_date, body.end_date, body.priority, current_user["sub"],
    )
    return get_activity(activity_id)


@app.get("/activities/{activity_id}", summary="Get a single activity (creator or admin)", tags=["Collaboration"])
def api_get_activity(activity_id: int, current_user: dict = Depends(get_current_user)):
    activity = get_activity(activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found.")
    _check_activity_owner_or_admin(current_user, activity)
    return activity


@app.put("/activities/{activity_id}", summary="Update an activity (creator or admin)", tags=["Collaboration"])
def api_update_activity(activity_id: int, body: ActivityIn, current_user: dict = Depends(get_current_user)):
    activity = get_activity(activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found.")
    _check_activity_owner_or_admin(current_user, activity)
    if body.priority not in ACTIVITY_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Valid: {ACTIVITY_PRIORITIES}")
    update_activity(activity_id, body.title, body.description, body.start_date, body.end_date, body.priority)
    return get_activity(activity_id)


@app.delete("/activities/{activity_id}", summary="Delete an activity (creator or admin)", tags=["Collaboration"])
def api_delete_activity(activity_id: int, current_user: dict = Depends(get_current_user)):
    activity = get_activity(activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found.")
    _check_activity_owner_or_admin(current_user, activity)
    delete_activity(activity_id)
    return {"deleted": activity_id}


@app.get("/activities/{activity_id}/tasks", summary="List an activity's tasks (your own, or all if admin)", tags=["Collaboration"])
def api_list_tasks(activity_id: int, current_user: dict = Depends(get_current_user)):
    if not get_activity(activity_id):
        raise HTTPException(status_code=404, detail="Activity not found.")
    return list_tasks_for_activity_and_user(
        activity_id, current_user["sub"], is_admin=current_user.get("role") == "admin",
    )


@app.post("/activities/{activity_id}/tasks", summary="Create a task under an activity (creator or admin)", tags=["Collaboration"])
def api_create_task(activity_id: int, body: TaskIn, current_user: dict = Depends(get_current_user)):
    activity = get_activity(activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found.")
    _check_activity_owner_or_admin(current_user, activity)
    if body.priority not in ACTIVITY_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Valid: {ACTIVITY_PRIORITIES}")
    try:
        task_id = create_task(
            activity_id, body.title, body.description, body.start_date, body.end_date, body.priority,
            current_user["sub"], assignee_usernames=body.assignee_usernames,
        )
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_task(task_id)


@app.get("/tasks/{task_id}", summary="Get a single task (creator, assignee, or admin)", tags=["Collaboration"])
def api_get_task(task_id: int, current_user: dict = Depends(get_current_user)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    assignees = {a["username"] for a in list_task_assignees(task_id)}
    if current_user["sub"] not in assignees:
        _check_task_owner_or_admin(current_user, task)
    return task


@app.put("/tasks/{task_id}", summary="Update a task (creator or admin)", tags=["Collaboration"])
def api_update_task(task_id: int, body: TaskIn, current_user: dict = Depends(get_current_user)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    _check_task_owner_or_admin(current_user, task)
    if body.priority not in ACTIVITY_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Valid: {ACTIVITY_PRIORITIES}")
    try:
        update_task(
            task_id, body.title, body.description, body.start_date, body.end_date, body.priority,
            assignee_usernames=body.assignee_usernames,
        )
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return get_task(task_id)


@app.put("/tasks/{task_id}/status", summary="Update a task's status (creator, assignee, or admin)", tags=["Collaboration"])
def api_update_task_status(task_id: int, body: TaskStatusIn, current_user: dict = Depends(get_current_user)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    assignees = {a["username"] for a in list_task_assignees(task_id)}
    if current_user["sub"] not in assignees:
        _check_task_owner_or_admin(current_user, task)
    if body.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {TASK_STATUSES}")
    update_task_status(task_id, body.status)
    return get_task(task_id)


@app.delete("/tasks/{task_id}", summary="Delete a task (creator or admin)", tags=["Collaboration"])
def api_delete_task(task_id: int, current_user: dict = Depends(get_current_user)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    _check_task_owner_or_admin(current_user, task)
    delete_task(task_id)
    return {"deleted": task_id}


# ═══════════════════════════════════════════════════════════════════════════
# 📁 Admin / More — positions, user accounts, self-service, documents
# ═══════════════════════════════════════════════════════════════════════════

class PositionIn(BaseModel):
    title: str
    role: str = "uploader"
    team_type: str = "election"


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "uploader"
    other_names: str = ""
    surname: str = ""
    email: str = ""
    position: str = ""
    id_passport_number: str = ""
    phone_number: str = ""
    gender: str = ""
    date_of_birth: date | None = None
    county: str = ""
    sub_county: str = ""
    ward: str = ""


class UserUpdateIn(BaseModel):
    other_names: str = ""
    surname: str = ""
    email: str = ""
    position: str = ""
    id_passport_number: str = ""
    phone_number: str = ""
    gender: str = ""
    date_of_birth: date | None = None
    county: str = ""
    sub_county: str = ""
    ward: str = ""


class PasswordResetIn(BaseModel):
    new_password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class StationAssignmentIn(BaseModel):
    polling_station_codes: list[str]


@app.get("/positions", summary="List all positions", tags=["Admin"])
def api_list_positions(team_type: str | None = Query(None), current_user: dict = Depends(get_current_user)):
    return list_positions(team_type=team_type)


@app.post("/positions", summary="Create a position (admin only)", tags=["Admin"])
def api_add_position(body: PositionIn, current_user: dict = Depends(require_admin)):
    if body.team_type not in POSITION_TEAM_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid team_type. Valid: {POSITION_TEAM_TYPES}")
    try:
        add_position(body.title, body.role, body.team_type)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return body


@app.put("/positions/{title}", summary="Update a position (admin only)", tags=["Admin"])
def api_update_position(title: str, body: PositionIn, current_user: dict = Depends(require_admin)):
    if body.team_type not in POSITION_TEAM_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid team_type. Valid: {POSITION_TEAM_TYPES}")
    try:
        update_position(title, body.title, body.role, body.team_type)
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return body


@app.delete("/positions/{title}", summary="Delete a position (admin only)", tags=["Admin"])
def api_delete_position(title: str, current_user: dict = Depends(require_admin)):
    delete_position(title)
    return {"deleted": title}


@app.get("/users", summary="List/search users (admin only)", tags=["Admin"])
def api_list_users(
    search: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_admin),
):
    return {
        "total": count_users(search),
        "items": [_public_user(u) for u in list_users(search, limit=limit, offset=offset)],
    }


@app.get("/users/{username}", summary="Get a user (admin or self)", tags=["Admin"])
def api_get_user(username: str, current_user: dict = Depends(get_current_user)):
    _check_self_or_admin(current_user, username)
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _public_user(user)


@app.post("/users", summary="Create a user (admin only)", tags=["Admin"])
def api_create_user(body: UserCreateIn, current_user: dict = Depends(require_admin)):
    try:
        create_user(**body.model_dump())
    except Exception as e:
        raise HTTPException(status_code=409 if "Duplicate entry" in str(e) else 400, detail=str(e))
    return _public_user(get_user(body.username))


@app.put("/users/{username}", summary="Update a user's profile (admin only)", tags=["Admin"])
def api_update_user(username: str, body: UserUpdateIn, current_user: dict = Depends(require_admin)):
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        update_user_profile(username, **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _public_user(get_user(username))


@app.delete("/users/{username}", summary="Delete a user (admin only)", tags=["Admin"])
def api_delete_user(username: str, current_user: dict = Depends(require_admin)):
    if current_user["sub"] == username:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    delete_user(username)
    return {"deleted": username}


@app.post("/users/{username}/reset-password", summary="Reset a user's password (admin only)", tags=["Admin"])
def api_reset_password(username: str, body: PasswordResetIn, current_user: dict = Depends(require_admin)):
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    update_password(username, body.new_password)
    return {"username": username, "password_reset": True}


@app.get("/me", summary="Get your own profile", tags=["Admin"])
def api_get_me(current_user: dict = Depends(get_current_user)):
    user = get_user(current_user["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _public_user(user)


@app.put("/me", summary="Update your own profile", tags=["Admin"])
def api_update_me(body: UserUpdateIn, current_user: dict = Depends(get_current_user)):
    try:
        update_user_profile(current_user["sub"], **body.model_dump())
    except Exception as e:
        raise _duplicate_or_bad_request(e)
    return _public_user(get_user(current_user["sub"]))


@app.put("/me/password", summary="Change your own password", tags=["Admin"])
def api_change_my_password(body: PasswordChangeIn, current_user: dict = Depends(get_current_user)):
    user = get_user(current_user["sub"])
    if not user or not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    update_password(current_user["sub"], body.new_password)
    return {"password_changed": True}


@app.get(
    "/users/{username}/team-assignments",
    summary="List every team (campaign/election) a user is assigned to, with their position (admin or self)", tags=["Admin"],
)
def api_get_user_team_assignments(username: str, current_user: dict = Depends(get_current_user)):
    _check_self_or_admin(current_user, username)
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    return list_team_assignments_for_user(username)


@app.get("/users/{username}/polling-stations", summary="List a user's assigned polling stations (admin or self)", tags=["Admin"])
def api_get_user_stations(username: str, current_user: dict = Depends(get_current_user)):
    _check_self_or_admin(current_user, username)
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    return get_user_polling_stations(username)


@app.put("/users/{username}/polling-stations", summary="Replace a user's assigned polling stations (admin only)", tags=["Admin"])
def api_set_user_stations(username: str, body: StationAssignmentIn, current_user: dict = Depends(require_admin)):
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    assign_user_polling_stations(username, body.polling_station_codes)
    return {"username": username, "polling_station_codes": get_user_polling_station_codes(username)}


@app.get("/users/{username}/documents", summary="List a user's attached documents (admin or self)", tags=["Admin"])
def api_list_user_documents(username: str, current_user: dict = Depends(get_current_user)):
    _check_self_or_admin(current_user, username)
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    return list_user_documents(username)


@app.post("/users/{username}/documents", summary="Attach a document to a user (admin or self)", tags=["Admin"])
async def api_upload_user_document(
    username: str,
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _check_self_or_admin(current_user, username)
    if not get_user(username):
        raise HTTPException(status_code=404, detail="User not found.")
    if not title.strip() or not file.filename:
        raise HTTPException(status_code=400, detail="A title and a file are both required.")
    contents = await file.read()
    stored_name = save_user_document_file(username, file.filename, contents)
    doc_id = add_user_document(username, title.strip(), stored_name, file.filename, current_user["sub"])
    return {"id": doc_id, "username": username, "title": title.strip(), "original_filename": file.filename}


@app.get("/documents/{doc_id}/download", summary="Download a document (admin or owning user)", tags=["Admin"])
def api_download_document(doc_id: int, current_user: dict = Depends(get_current_user)):
    doc = get_user_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    _check_self_or_admin(current_user, doc["username"])
    result = get_user_document_bytes(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document file is missing on disk.")
    file_bytes, display_name = result
    return Response(
        content=file_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{display_name}"'},
    )


@app.delete("/documents/{doc_id}", summary="Delete a document (admin or owning user)", tags=["Admin"])
def api_delete_document(doc_id: int, current_user: dict = Depends(get_current_user)):
    doc = get_user_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    _check_self_or_admin(current_user, doc["username"])
    delete_user_document(doc_id)
    return {"deleted": doc_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
