"""MySQL database helpers: connection, schema creation, save, and tally update."""

import calendar as _calendar
import os
import time
from datetime import date, time as dt_time, timedelta
from pathlib import Path

import mysql.connector

import cloudinary_storage
from form_types import FORM_TYPE_MAP, TALLY_CONFIG

# Anchored to this file's directory (not the process's CWD) so uploads land in
# the same place regardless of where the app is launched from. Override with
# DOCS_DIR to point at a separate persistent volume in production.
DOCS_DIR = Path(os.environ.get("DOCS_DIR") or Path(__file__).resolve().parent / "docs")
USER_DOCS_DIR = DOCS_DIR / "user_documents"
APPLICANT_DOCS_DIR = DOCS_DIR / "applicant_documents"
CAMPAIGN_BANNERS_DIR = DOCS_DIR / "campaign_banners"
CAMPAIGN_MEDIA_DIR = DOCS_DIR / "campaign_media"
FEED_IMAGES_DIR = DOCS_DIR / "feed_images"
PARTY_LOGOS_DIR = DOCS_DIR / "party_logos"
CANDIDATE_PHOTOS_DIR = DOCS_DIR / "candidate_photos"


def get_db_connection():
    db_name = os.environ.get("DB_NAME", "tallydb")
    # conn = mysql.connector.connect(
    #     host=os.environ.get("DB_HOST", "localhost"),
    #     user=os.environ.get("DB_USER", "root"),
    #     password=os.environ.get("DB_PASSWORD", ""),
    # )
    params = dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    # Hosted MySQL (TiDB Cloud, Aiven, ...) requires TLS — verify against the
    # certifi CA bundle so it works on any host without a system cert path.
    if os.environ.get("DB_SSL", "").lower() == "true":
        import certifi
        params.update(ssl_ca=certifi.where(), ssl_verify_cert=True, ssl_verify_identity=True)
    # Connect straight to the database and only CREATE it when it's missing.
    # Running CREATE DATABASE on every connection needs an exclusive schema
    # lock, which blocks forever behind any other open connection that has an
    # uncommitted read in this schema (e.g. a nested connection inside a
    # `with _conn()` block) — that deadlocked the Streamlit dashboard.
    try:
        return mysql.connector.connect(database=db_name, **params)
    except mysql.connector.Error as e:
        if e.errno != 1049:  # ER_BAD_DB_ERROR: unknown database
            raise
    conn = mysql.connector.connect(**params)
    conn.cursor().execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    conn.database = db_name
    return conn


# ── Schema builders ───────────────────────────────────────────────────────────

def _create_forms_sql(forms_table: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS `{forms_table}` (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    source_file              VARCHAR(512) UNIQUE,
    form_number              VARCHAR(50),
    polling_station          VARCHAR(255),
    polling_station_code     VARCHAR(50),
    ward                     VARCHAR(100),
    ward_code                VARCHAR(20),
    constituency             VARCHAR(100),
    constituency_code        VARCHAR(20),
    county                   VARCHAR(100),
    county_code              VARCHAR(20),
    total_valid_votes        INT,
    registered_voters        INT,
    rejected_ballots         INT,
    objected_rejections      INT,
    disputed_votes           INT,
    presiding_officer        VARCHAR(255),
    deputy_presiding_officer VARCHAR(255),
    date                     VARCHAR(20),
    comments                 TEXT,
    uploaded_by              VARCHAR(100),
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _create_votes_sql(votes_table: str, forms_table: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS `{votes_table}` (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    form_id          INT NOT NULL,
    candidate_number INT,
    candidate_name   VARCHAR(255),
    votes            INT,
    FOREIGN KEY (form_id) REFERENCES `{forms_table}`(id) ON DELETE CASCADE
)
"""


def _create_tally_sql(tally_table: str, group_key_col: str | None, group_name_col: str | None) -> str:
    if group_key_col:
        return f"""
CREATE TABLE IF NOT EXISTS `{tally_table}` (
    `{group_key_col}`   VARCHAR(20)  NOT NULL,
    `{group_name_col}`  VARCHAR(100),
    candidate_number    INT          NOT NULL,
    candidate_name      VARCHAR(255),
    total_votes         INT          DEFAULT 0,
    total_registered    INT          DEFAULT 0,
    total_valid_votes   INT          DEFAULT 0,
    total_rejected      INT          DEFAULT 0,
    stations_counted    INT          DEFAULT 0,
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`{group_key_col}`, candidate_number)
)
"""
    return f"""
CREATE TABLE IF NOT EXISTS `{tally_table}` (
    candidate_number    INT          NOT NULL PRIMARY KEY,
    candidate_name      VARCHAR(255),
    total_votes         INT          DEFAULT 0,
    total_registered    INT          DEFAULT 0,
    total_valid_votes   INT          DEFAULT 0,
    total_rejected      INT          DEFAULT 0,
    stations_counted    INT          DEFAULT 0,
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
)
"""


def _ensure_tables(cursor, forms_table: str, votes_table: str):
    cursor.execute(_create_forms_sql(forms_table))
    cursor.execute(_create_votes_sql(votes_table, forms_table))
    # Migrate existing tables that predate the uploaded_by column
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = 'uploaded_by'",
        (forms_table,),
    )
    if not cursor.fetchone():
        cursor.execute(
            f"ALTER TABLE `{forms_table}` ADD COLUMN `uploaded_by` VARCHAR(100) AFTER `comments`"
        )


# ── Tally ─────────────────────────────────────────────────────────────────────

def _update_tally(cursor, structured: dict, form_type: str):
    """Recompute the tally for the geographic group that this form belongs to."""
    tally_table, group_key_col, group_name_col = TALLY_CONFIG[form_type]
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]

    cursor.execute(_create_tally_sql(tally_table, group_key_col, group_name_col))

    if group_key_col:
        group_key_val = structured.get(group_key_col)
        if not group_key_val:
            return
        cursor.execute(
            f"DELETE FROM `{tally_table}` WHERE `{group_key_col}` = %s", (group_key_val,)
        )
        cursor.execute(f"""
            INSERT INTO `{tally_table}`
                (`{group_key_col}`, `{group_name_col}`, candidate_number, candidate_name,
                 total_votes, total_registered, total_valid_votes, total_rejected, stations_counted)
            SELECT
                f.`{group_key_col}`, f.`{group_name_col}`,
                cv.candidate_number, cv.candidate_name,
                SUM(cv.votes),
                SUM(f.registered_voters),
                SUM(f.total_valid_votes),
                SUM(f.rejected_ballots),
                COUNT(DISTINCT f.id)
            FROM `{forms_table}` f
            JOIN `{votes_table}` cv ON cv.form_id = f.id
            WHERE f.`{group_key_col}` = %s
            GROUP BY f.`{group_key_col}`, f.`{group_name_col}`, cv.candidate_number, cv.candidate_name
        """, (group_key_val,))
    else:
        cursor.execute(f"DELETE FROM `{tally_table}`")
        cursor.execute(f"""
            INSERT INTO `{tally_table}`
                (candidate_number, candidate_name,
                 total_votes, total_registered, total_valid_votes, total_rejected, stations_counted)
            SELECT
                cv.candidate_number, cv.candidate_name,
                SUM(cv.votes),
                SUM(f.registered_voters),
                SUM(f.total_valid_votes),
                SUM(f.rejected_ballots),
                COUNT(DISTINCT f.id)
            FROM `{forms_table}` f
            JOIN `{votes_table}` cv ON cv.form_id = f.id
            GROUP BY cv.candidate_number, cv.candidate_name
        """)


# ── Public API ────────────────────────────────────────────────────────────────

def is_already_processed(source_file: str, form_type: str) -> bool:
    """Return True if this file path is already saved in its form-type table."""
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        _ensure_tables(cursor, forms_table, votes_table)
        cursor.execute(
            f"SELECT id FROM `{forms_table}` WHERE source_file = %s", (source_file,)
        )
        found = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return found
    except Exception:
        return False


def find_duplicate_form_number(form_number: str, form_type: str) -> dict | None:
    """Return the existing row (id, source_file) if this form_number is already in the DB, else None."""
    if not form_number:
        return None
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        _ensure_tables(cursor, forms_table, votes_table)
        cursor.execute(
            f"SELECT id, source_file FROM `{forms_table}` WHERE form_number = %s",
            (form_number,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row
    except Exception:
        return None


def save_to_db(structured: dict, source_file: str, form_type: str, uploaded_by: str = "") -> int:
    """Insert parsed results into the correct form-type tables. Returns new form id."""
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_tables(cursor, forms_table, votes_table)

    form_params = {k: v for k, v in structured.items() if k != "candidates"}
    form_params["source_file"] = source_file
    form_params["uploaded_by"] = uploaded_by or None
    cursor.execute(f"""
        INSERT INTO `{forms_table}` (
            source_file,
            form_number, polling_station, polling_station_code,
            ward, ward_code, constituency, constituency_code,
            county, county_code,
            total_valid_votes, registered_voters, rejected_ballots,
            objected_rejections, disputed_votes,
            presiding_officer, deputy_presiding_officer,
            date, comments,
            uploaded_by
        ) VALUES (
            %(source_file)s,
            %(form_number)s, %(polling_station)s, %(polling_station_code)s,
            %(ward)s, %(ward_code)s, %(constituency)s, %(constituency_code)s,
            %(county)s, %(county_code)s,
            %(total_valid_votes)s, %(registered_voters)s, %(rejected_ballots)s,
            %(objected_rejections)s, %(disputed_votes)s,
            %(presiding_officer)s, %(deputy_presiding_officer)s,
            %(date)s, %(comments)s,
            %(uploaded_by)s
        )
    """, form_params)
    form_id = cursor.lastrowid

    for c in structured.get("candidates", []):
        cursor.execute(
            f"INSERT INTO `{votes_table}` (form_id, candidate_number, candidate_name, votes) "
            "VALUES (%s, %s, %s, %s)",
            (form_id, c.get("number"), c.get("name"), c.get("votes")),
        )

    _update_tally(cursor, structured, form_type)

    conn.commit()
    cursor.close()
    conn.close()
    return form_id


# ── Users / Auth ──────────────────────────────────────────────────────────────

def _ensure_users_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `users` (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            username      VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role          ENUM('admin', 'uploader', 'viewer') DEFAULT 'uploader',
            other_names   VARCHAR(100),
            surname       VARCHAR(100),
            email         VARCHAR(255),
            position      VARCHAR(100),
            id_passport_number VARCHAR(50),
            phone_number       VARCHAR(30),
            gender             VARCHAR(20),
            date_of_birth      DATE,
            county             VARCHAR(100),
            sub_county         VARCHAR(100),
            ward               VARCHAR(100),
            ward_id            VARCHAR(4),
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("other_names", "VARCHAR(100)"),
        ("surname",      "VARCHAR(100)"),
        ("email",      "VARCHAR(255)"),
        ("position",   "VARCHAR(100)"),
        ("id_passport_number", "VARCHAR(50)"),
        ("phone_number",       "VARCHAR(30)"),
        ("gender",             "VARCHAR(20)"),
        ("date_of_birth",      "DATE"),
        ("county",             "VARCHAR(100)"),
        ("sub_county",         "VARCHAR(100)"),
        ("ward",               "VARCHAR(100)"),
        ("ward_id",            "VARCHAR(4)"),
        ("occupation",         "VARCHAR(150)"),
        ("last_seen",          "TIMESTAMP NULL"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `users` ADD COLUMN `{col}` {definition}")

    # Link to the demography reference table (wards table must already exist).
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'users' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_users_ward'"
    )
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE `users` ADD CONSTRAINT `fk_users_ward` "
            "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) "
            "ON DELETE SET NULL ON UPDATE CASCADE"
        )


def init_users():
    """Create users table and seed a default admin if no users exist yet."""
    from auth import hash_password
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_users_table(cursor)
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM `users`")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO `users` (username, password_hash, role) VALUES (%s, %s, 'admin')",
            ("admin", hash_password("admin123")),
        )
        conn.commit()
        print("\n[auth] Default admin created — username: admin  password: admin123")
        print("[auth] Change this password immediately via the app.\n")
    cursor.close()
    conn.close()


def get_user(username: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_users_table(cursor)
    cursor.execute("SELECT * FROM `users` WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


# ── Revoked tokens (shared across processes, unlike an in-memory set) ──────────
# expires_at is a Unix timestamp (not DATETIME) so comparisons never depend on
# the MySQL server's configured timezone.

def _ensure_revoked_tokens_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `revoked_tokens` (
            token_hash   CHAR(64) PRIMARY KEY,
            expires_at   BIGINT NOT NULL
        )
    """)


def init_revoked_tokens():
    """Create the revoked_tokens table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_revoked_tokens_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def add_revoked_token(token_hash: str, expires_at: int) -> None:
    """Record a revoked token (by hash) until it would have naturally expired.
    Opportunistically prunes already-expired entries so the table stays small."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_revoked_tokens_table(cursor)
    now = int(time.time())
    cursor.execute("DELETE FROM `revoked_tokens` WHERE expires_at <= %s", (now,))
    cursor.execute(
        "INSERT INTO `revoked_tokens` (token_hash, expires_at) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE expires_at = VALUES(expires_at)",
        (token_hash, expires_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


def is_token_revoked(token_hash: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_revoked_tokens_table(cursor)
    cursor.execute(
        "SELECT 1 FROM `revoked_tokens` WHERE token_hash = %s AND expires_at > %s",
        (token_hash, int(time.time())),
    )
    found = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return found


# ── Presence (heartbeat-based online/offline) ───────────────────────────────

ONLINE_THRESHOLD_SECONDS = 60


def touch_presence(username: str) -> None:
    """Mark this user as active right now. Called periodically from a live
    session so `last_seen` acts as a heartbeat rather than a one-off login time."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `users` SET last_seen = CURRENT_TIMESTAMP WHERE username = %s", (username,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def list_online_usernames(threshold_seconds: int = ONLINE_THRESHOLD_SECONDS) -> set[str]:
    """Usernames with a heartbeat inside the last `threshold_seconds`."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username FROM `users` "
        "WHERE last_seen IS NOT NULL AND last_seen > NOW() - INTERVAL %s SECOND",
        (threshold_seconds,),
    )
    usernames = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return usernames


def list_users(search: str = "", limit: int | None = None, offset: int = 0) -> list[dict]:
    """List users, optionally filtered by a search term matched against
    username/name/email/position/role, and optionally paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE username LIKE %s OR other_names LIKE %s OR surname LIKE %s "
            "OR email LIKE %s OR position LIKE %s OR role LIKE %s"
        )
        params = (like, like, like, like, like, like)
    query = (
        "SELECT id, username, other_names, surname, email, position, role, created_at "
        f"FROM `users` {where} ORDER BY created_at"
    )
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users


def count_users(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE username LIKE %s OR other_names LIKE %s OR surname LIKE %s "
            "OR email LIKE %s OR position LIKE %s OR role LIKE %s"
        )
        params = (like, like, like, like, like, like)
    cursor.execute(f"SELECT COUNT(*) FROM `users` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


# ── Team assignments (many-to-many: a user may hold a position on more than
# one team at once, e.g. both the campaign team and the election team) ──────

def _ensure_team_assignments_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `team_assignments` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            position   VARCHAR(200) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_team_assignment` (username, position)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_team_assignment_user",
         "ALTER TABLE `team_assignments` ADD CONSTRAINT `fk_team_assignment_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_team_assignment_position",
         "ALTER TABLE `team_assignments` ADD CONSTRAINT `fk_team_assignment_position` "
         "FOREIGN KEY (position) REFERENCES positions(title) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'team_assignments' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_team_assignments():
    """Create the team_assignments table (depends on users + positions)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_team_assignments_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_user_team_position(username: str, team_type: str) -> dict | None:
    """This user's single position within one team (campaign/election), if any."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ta.position, p.role, p.team_type FROM `team_assignments` ta "
        "JOIN `positions` p ON p.title = ta.position "
        "WHERE ta.username = %s AND p.team_type = %s LIMIT 1",
        (username, team_type),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def list_team_assignments_for_user(username: str) -> list[dict]:
    """Every team this user belongs to, with their position on each."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ta.position, p.role, p.team_type FROM `team_assignments` ta "
        "JOIN `positions` p ON p.title = ta.position "
        "WHERE ta.username = %s ORDER BY p.team_type, p.sort_order",
        (username,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def assign_user_to_team(username: str, team_type: str, position: str) -> None:
    """Set this user's position within a team, replacing any prior position
    they held on that same team. A user may hold at most one position per
    team, but a separate position on each of several teams at once — this
    only touches the given team_type, so other team memberships are untouched.
    A position tagged 'both' counts toward whichever team_type is passed in."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE ta FROM `team_assignments` ta JOIN `positions` p ON p.title = ta.position "
        "WHERE ta.username = %s AND p.team_type IN (%s, 'both')",
        (username, team_type),
    )
    cursor.execute(
        "INSERT INTO `team_assignments` (username, position) VALUES (%s, %s)",
        (username, position),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_user_from_team(username: str, team_type: str) -> None:
    """Unassign this user from a team, leaving their account and any other
    team membership(s) intact."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE ta FROM `team_assignments` ta JOIN `positions` p ON p.title = ta.position "
        "WHERE ta.username = %s AND p.team_type IN (%s, 'both')",
        (username, team_type),
    )
    conn.commit()
    cursor.close()
    conn.close()


def _team_users_where(team_type: str, search: str = "") -> tuple[str, tuple]:
    # A position tagged 'both' counts toward either team.
    clauses, params = ["p.team_type IN (%s, 'both')"], [team_type]
    if search:
        like = f"%{search}%"
        clauses.append(
            "(u.username LIKE %s OR u.other_names LIKE %s OR u.surname LIKE %s "
            "OR u.email LIKE %s OR ta.position LIKE %s OR u.role LIKE %s)"
        )
        params += [like, like, like, like, like, like]
    return "WHERE " + " AND ".join(clauses), tuple(params)


def list_users_by_team_type(
    team_type: str, search: str = "", limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List users assigned to a given team_type ('campaign' or 'election') via
    team_assignments, each annotated with their position on that team,
    optionally filtered/paginated. A user assigned to both teams appears in
    both listings (with a different position in each, if applicable)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _team_users_where(team_type, search)
    query = (
        "SELECT u.id, u.username, u.other_names, u.surname, u.email, "
        "ta.position AS position, u.role, u.created_at "
        "FROM `users` u "
        "JOIN `team_assignments` ta ON ta.username = u.username "
        "JOIN `positions` p ON p.title = ta.position "
        f"{where} ORDER BY u.created_at"
    )
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users


def count_users_by_team_type(team_type: str, search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _team_users_where(team_type, search)
    cursor.execute(
        "SELECT COUNT(*) FROM `users` u "
        "JOIN `team_assignments` ta ON ta.username = u.username "
        f"JOIN `positions` p ON p.title = ta.position {where}",
        params,
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def create_user(
    username: str,
    password: str,
    role: str = "uploader",
    other_names: str = "",
    surname: str = "",
    email: str = "",
    position: str = "",
    id_passport_number: str = "",
    phone_number: str = "",
    gender: str = "",
    date_of_birth=None,
    county: str = "",
    sub_county: str = "",
    ward: str = "",
    ward_id: str | None = None,
    occupation: str = "",
) -> None:
    from auth import hash_password
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `users` (username, password_hash, role, other_names, surname, email, position, "
        "id_passport_number, phone_number, gender, date_of_birth, county, sub_county, ward, ward_id, occupation) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (username, hash_password(password), role,
         other_names or None, surname or None, email or None, position or None,
         id_passport_number or None, phone_number or None, gender or None,
         date_of_birth or None, county or None, sub_county or None, ward or None, ward_id,
         occupation or None),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_user_profile(
    username: str,
    other_names: str = "",
    surname: str = "",
    email: str = "",
    position: str = "",
    id_passport_number: str = "",
    phone_number: str = "",
    gender: str = "",
    date_of_birth=None,
    county: str = "",
    sub_county: str = "",
    ward: str = "",
    ward_id: str | None = None,
    occupation: str = "",
) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `users` SET other_names=%s, surname=%s, email=%s, position=%s, "
        "id_passport_number=%s, phone_number=%s, gender=%s, date_of_birth=%s, "
        "county=%s, sub_county=%s, ward=%s, ward_id=%s, occupation=%s WHERE username=%s",
        (other_names or None, surname or None, email or None, position or None,
         id_passport_number or None, phone_number or None, gender or None,
         date_of_birth or None, county or None, sub_county or None, ward or None, ward_id,
         occupation or None, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_user(username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT filename FROM `user_documents` WHERE username = %s", (username,))
    doc_files = [r["filename"] for r in cursor.fetchall()]
    for fname in doc_files:
        if cloudinary_storage.is_remote_ref(fname):
            cloudinary_storage.destroy(fname)
        else:
            (USER_DOCS_DIR / username / fname).unlink(missing_ok=True)

    cursor.execute("DELETE FROM `users` WHERE username = %s", (username,))
    cursor.execute("DELETE FROM `user_polling_stations` WHERE username = %s", (username,))
    cursor.execute("DELETE FROM `user_documents` WHERE username = %s", (username,))
    conn.commit()
    cursor.close()
    conn.close()
    try:
        (USER_DOCS_DIR / username).rmdir()
    except OSError:
        pass


def update_password(username: str, new_password: str) -> None:
    from auth import hash_password
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `users` SET password_hash = %s WHERE username = %s",
        (hash_password(new_password), username),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Chat messages (direct messages between two users) ──────────────────────────

def _ensure_chat_messages_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `chat_messages` (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            sender_username     VARCHAR(100) NOT NULL,
            recipient_username  VARCHAR(100) NOT NULL,
            message             TEXT NOT NULL,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (sender_username, recipient_username),
            INDEX (recipient_username, sender_username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_chat_message_sender",
         "ALTER TABLE `chat_messages` ADD CONSTRAINT `fk_chat_message_sender` "
         "FOREIGN KEY (sender_username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_chat_message_recipient",
         "ALTER TABLE `chat_messages` ADD CONSTRAINT `fk_chat_message_recipient` "
         "FOREIGN KEY (recipient_username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'chat_messages' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_chat_messages():
    """Create the chat_messages table (depends on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_chat_messages_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def send_chat_message(sender_username: str, recipient_username: str, message: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `chat_messages` (sender_username, recipient_username, message) "
        "VALUES (%s, %s, %s)",
        (sender_username, recipient_username, message),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def list_chat_messages(user_a: str, user_b: str, limit: int = 200) -> list[dict]:
    """Conversation between two users, oldest first."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM ("
        "  SELECT * FROM `chat_messages` "
        "  WHERE (sender_username = %s AND recipient_username = %s) "
        "     OR (sender_username = %s AND recipient_username = %s) "
        "  ORDER BY created_at DESC, id DESC LIMIT %s"
        ") t ORDER BY created_at, id",
        (user_a, user_b, user_b, user_a, limit),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── Chat groups (group chats among multiple users) ──────────────────────────

def _ensure_chat_groups_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `chat_groups` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(150) NOT NULL,
            created_by  VARCHAR(100) NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `chat_group_members` (
            group_id    INT NOT NULL,
            username    VARCHAR(100) NOT NULL,
            joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `chat_group_messages` (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            group_id            INT NOT NULL,
            sender_username     VARCHAR(100) NOT NULL,
            message             TEXT NOT NULL,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (group_id, created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for table, fk_name, ddl in [
        ("chat_groups", "fk_chat_group_creator",
         "ALTER TABLE `chat_groups` ADD CONSTRAINT `fk_chat_group_creator` "
         "FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("chat_group_members", "fk_chat_group_member_group",
         "ALTER TABLE `chat_group_members` ADD CONSTRAINT `fk_chat_group_member_group` "
         "FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE"),
        ("chat_group_members", "fk_chat_group_member_user",
         "ALTER TABLE `chat_group_members` ADD CONSTRAINT `fk_chat_group_member_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("chat_group_messages", "fk_chat_group_message_group",
         "ALTER TABLE `chat_group_messages` ADD CONSTRAINT `fk_chat_group_message_group` "
         "FOREIGN KEY (group_id) REFERENCES chat_groups(id) ON DELETE CASCADE"),
        ("chat_group_messages", "fk_chat_group_message_sender",
         "ALTER TABLE `chat_group_messages` ADD CONSTRAINT `fk_chat_group_message_sender` "
         "FOREIGN KEY (sender_username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = %s "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (table, fk_name),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_chat_groups():
    """Create the chat group tables (depends on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_chat_groups_tables(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def create_chat_group(name: str, created_by: str, member_usernames: list[str]) -> int:
    """Create a group chat and add the creator plus the given members."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `chat_groups` (name, created_by) VALUES (%s, %s)",
        (name, created_by),
    )
    group_id = cursor.lastrowid
    members = {created_by, *member_usernames}
    cursor.executemany(
        "INSERT IGNORE INTO `chat_group_members` (group_id, username) VALUES (%s, %s)",
        [(group_id, u) for u in members],
    )
    conn.commit()
    cursor.close()
    conn.close()
    return group_id


def add_chat_group_members(group_id: int, usernames: list[str]) -> None:
    if not usernames:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT IGNORE INTO `chat_group_members` (group_id, username) VALUES (%s, %s)",
        [(group_id, u) for u in usernames],
    )
    conn.commit()
    cursor.close()
    conn.close()


def list_user_groups(username: str) -> list[dict]:
    """Groups the given user belongs to, with member counts and each group's
    last activity time, ordered by last activity (newest first)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT g.id, g.name, g.created_by, g.created_at, "
        "(SELECT COUNT(*) FROM `chat_group_members` m2 WHERE m2.group_id = g.id) AS member_count, "
        "(SELECT MAX(created_at) FROM `chat_group_messages` gm WHERE gm.group_id = g.id) AS last_message_at "
        "FROM `chat_groups` g "
        "JOIN `chat_group_members` m ON m.group_id = g.id AND m.username = %s "
        "ORDER BY COALESCE("
        "  (SELECT MAX(created_at) FROM `chat_group_messages` gm2 WHERE gm2.group_id = g.id), "
        "  g.created_at"
        ") DESC",
        (username,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_dm_conversations(username: str) -> list[dict]:
    """The given user's direct-message conversation peers, with each
    conversation's last activity time, newest first."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT "
        "  CASE WHEN sender_username = %s THEN recipient_username ELSE sender_username END AS peer, "
        "  MAX(created_at) AS created_at "
        "FROM `chat_messages` "
        "WHERE sender_username = %s OR recipient_username = %s "
        "GROUP BY peer "
        "ORDER BY created_at DESC",
        (username, username, username),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_group_members(group_id: int) -> list[dict]:
    """Members of a group chat, with display-name fields, alphabetical."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT u.username, u.other_names, u.surname, u.position, u.role "
        "FROM `chat_group_members` m "
        "JOIN `users` u ON u.username = m.username "
        "WHERE m.group_id = %s "
        "ORDER BY u.other_names, u.surname",
        (group_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def send_group_chat_message(group_id: int, sender_username: str, message: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `chat_group_messages` (group_id, sender_username, message) VALUES (%s, %s, %s)",
        (group_id, sender_username, message),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def list_group_chat_messages(group_id: int, limit: int = 200) -> list[dict]:
    """Messages in a group chat, oldest first, with sender display-name fields."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM ("
        "  SELECT gm.*, u.other_names AS sender_other_names, u.surname AS sender_surname "
        "  FROM `chat_group_messages` gm "
        "  JOIN `users` u ON u.username = gm.sender_username "
        "  WHERE gm.group_id = %s "
        "  ORDER BY gm.created_at DESC, gm.id DESC LIMIT %s"
        ") t ORDER BY created_at, id",
        (group_id, limit),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── Positions ─────────────────────────────────────────────────────────────────

POSITION_TEAM_TYPES = ["campaign", "election", "both"]

# (title, default_role, team_type)
_SEED_POSITIONS = [
    ("Chairman",                          "admin",    "election"),
    ("Commissioner",                      "admin",    "election"),
    ("Chief Executive Officer",           "admin",    "election"),
    ("Commission Secretary",              "admin",    "election"),
    ("Director/Manager",                  "admin",    "election"),
    ("Presiding Officer (PO)",            "uploader", "election"),
    ("Deputy Presiding Officers (DPO)",   "uploader", "election"),
    ("Deputy Presiding Officer",          "uploader", "election"),
    ("Returning Officer (RO)",            "uploader", "election"),
    ("Deputy Returning Officer (DRO)",    "uploader", "election"),
    ("Assistant Returning Officer (ARO)", "uploader", "election"),
    ("Election Officer",                  "uploader", "election"),
    ("Voter Registration Assistant (VRA)","uploader", "election"),
    ("Polling Clerk",                     "uploader", "election"),
    ("Support Electoral Trainer (SET)",   "uploader", "election"),
    ("Observer",                          "viewer",   "election"),
    ("Voter Educator",                    "viewer",   "election"),
    ("Other",                             "uploader", "election"),
    ("Campaign Manager",                  "admin",    "campaign"),
    ("Deputy Campaign Manager",           "admin",    "campaign"),
    ("Field Coordinator",                 "uploader", "campaign"),
    ("Campaign Agent",                    "uploader", "campaign"),
    ("Volunteer Coordinator",             "uploader", "campaign"),
    ("Social Media Coordinator",          "uploader", "campaign"),
    ("Campaign Volunteer",                "viewer",   "campaign"),
]


def init_positions():
    """Create positions table and seed defaults if empty."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `positions` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            title      VARCHAR(200) UNIQUE NOT NULL,
            role       ENUM('admin','uploader','viewer') DEFAULT 'uploader',
            team_type  ENUM('campaign','election','both') DEFAULT 'election',
            sort_order INT DEFAULT 0
        )
    """)
    # Add columns to existing tables that pre-date this schema
    for col, definition in [
        ("role",      "ENUM('admin','uploader','viewer') DEFAULT 'uploader'"),
        ("team_type", "ENUM('campaign','election','both') DEFAULT 'election'"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'positions' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `positions` ADD COLUMN `{col}` {definition}")
    # Widen the team_type enum for tables created before 'both' was added
    cursor.execute(
        "SELECT COLUMN_TYPE FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'positions' AND column_name = 'team_type'"
    )
    row = cursor.fetchone()
    if row and "'both'" not in row[0]:
        cursor.execute(
            "ALTER TABLE `positions` MODIFY COLUMN `team_type` "
            "ENUM('campaign','election','both') DEFAULT 'election'"
        )
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM `positions`")
    if cursor.fetchone()[0] == 0:
        for i, (title, role, team_type) in enumerate(_SEED_POSITIONS):
            cursor.execute(
                "INSERT INTO `positions` (title, role, team_type, sort_order) VALUES (%s, %s, %s, %s)",
                (title, role, team_type, i),
            )
        conn.commit()
    cursor.close()
    conn.close()


def list_positions(team_type: str | None = None) -> list[dict]:
    """Return [{"title": ..., "role": ..., "team_type": ...}, ...] ordered by
    sort_order, optionally filtered to a single team_type ('campaign'/'election').
    Positions tagged 'both' are included in either filtered result."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if team_type:
        where = "WHERE team_type IN (%s, 'both')"
        params = (team_type,)
    cursor.execute(
        f"SELECT title, role, team_type FROM `positions` {where} ORDER BY sort_order, title",
        params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def add_position(title: str, role: str = "uploader", team_type: str = "election") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `positions` (title, role, team_type, sort_order) "
        "VALUES (%s, %s, %s, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM `positions` AS p))",
        (title, role, team_type),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_position(old_title: str, new_title: str, role: str, team_type: str = "election") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `positions` SET title = %s, role = %s, team_type = %s WHERE title = %s",
        (new_title, role, team_type, old_title),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_position(title: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `positions` WHERE title = %s", (title,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Panel assignments (panelist ↔ recruitment position, many-to-many) ──────────

PANEL_ROLES = ["chairman", "secretary", "member"]
_PANEL_ROLE_ENUM_SQL = "ENUM({}) DEFAULT 'member'".format(
    ",".join(f"'{r}'" for r in PANEL_ROLES)
)


def _ensure_panel_assignments_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `panel_assignments` (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            username       VARCHAR(100) NOT NULL,
            position       VARCHAR(200) NOT NULL,
            panel_role     {_PANEL_ROLE_ENUM_SQL},
            interview_date DATE NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_panel_assignment` (username, position)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_panel_assignment_user",
         "ALTER TABLE `panel_assignments` ADD CONSTRAINT `fk_panel_assignment_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_panel_assignment_position",
         "ALTER TABLE `panel_assignments` ADD CONSTRAINT `fk_panel_assignment_position` "
         "FOREIGN KEY (position) REFERENCES positions(title) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'panel_assignments' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_panel_assignments():
    """Create the panel_assignments table (depends on users + positions)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_panel_assignments_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_panel_assignments_for_user(username: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `panel_assignments` WHERE username = %s ORDER BY position",
        (username,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def set_panelist_assignments(username: str, assignments: list[dict]) -> None:
    """Replace a panelist's position assignments with exactly `assignments`
    (each a dict with position/panel_role/interview_date)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `panel_assignments` WHERE username = %s", (username,))
    if assignments:
        cursor.executemany(
            "INSERT INTO `panel_assignments` (username, position, panel_role, interview_date) "
            "VALUES (%s, %s, %s, %s)",
            [(username, a["position"], a.get("panel_role") or "member", a.get("interview_date"))
             for a in assignments],
        )
    conn.commit()
    cursor.close()
    conn.close()


def is_panelist(username: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM `panel_assignments` WHERE username = %s LIMIT 1", (username,))
    found = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return found


def get_panel_assignment(username: str, position: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `panel_assignments` WHERE username = %s AND position = %s",
        (username, position),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def list_panelists(search: str = "", limit: int | None = None, offset: int = 0) -> list[dict]:
    """Distinct users who have at least one panel assignment, optionally
    filtered by a search term matched against name/email/occupation/position,
    each annotated with its full `assignments` list for display."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE u.other_names LIKE %s OR u.surname LIKE %s OR u.email LIKE %s "
            "OR u.occupation LIKE %s OR pa.position LIKE %s"
        )
        params = (like, like, like, like, like)
    query = (
        "SELECT DISTINCT u.username, u.other_names, u.surname, u.email, u.gender, u.occupation, "
        "u.county, u.sub_county, u.ward, u.created_at "
        "FROM `users` u JOIN `panel_assignments` pa ON pa.username = u.username "
        f"{where} ORDER BY u.created_at"
    )
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    panelists = cursor.fetchall()
    cursor.close()
    conn.close()

    if panelists:
        usernames = [p["username"] for p in panelists]
        placeholders = ",".join(["%s"] * len(usernames))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT * FROM `panel_assignments` WHERE username IN ({placeholders}) ORDER BY position",
            usernames,
        )
        by_user: dict[str, list[dict]] = {}
        for row in cursor.fetchall():
            by_user.setdefault(row["username"], []).append(row)
        cursor.close()
        conn.close()
        for p in panelists:
            p["assignments"] = by_user.get(p["username"], [])
    return panelists


def count_panelists(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE u.other_names LIKE %s OR u.surname LIKE %s OR u.email LIKE %s "
            "OR u.occupation LIKE %s OR pa.position LIKE %s"
        )
        params = (like, like, like, like, like)
    cursor.execute(
        "SELECT COUNT(DISTINCT u.username) FROM `users` u "
        f"JOIN `panel_assignments` pa ON pa.username = u.username {where}",
        params,
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


# ── Job descriptions ─────────────────────────────────────────────────────────

ATTACHMENT_REQUIREMENT_OPTIONS = [
    "CV",
    "Application Letter",
    "Cover Letter",
    "Academic Certificates",
    "Professional Certificates",
    "Academic Transcripts",
    "National ID/Passport Copy",
    "Recommendation Letter",
]


def _ensure_job_descriptions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `job_descriptions` (
            id                      INT AUTO_INCREMENT PRIMARY KEY,
            position                VARCHAR(200) NOT NULL,
            description             TEXT,
            num_applicants_required INT DEFAULT 1,
            application_deadline    DATE,
            attachment_requirements VARCHAR(500),
            published               TINYINT(1) NOT NULL DEFAULT 0,
            created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("position",                "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("description",             "TEXT"),
        ("num_applicants_required", "INT DEFAULT 1"),
        ("application_deadline",    "DATE"),
        ("attachment_requirements", "VARCHAR(500)"),
        ("published",               "TINYINT(1) NOT NULL DEFAULT 0"),
        ("updated_at",              "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'job_descriptions' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `job_descriptions` ADD COLUMN `{col}` {definition}")

    # Link to the positions reference table (positions table must already exist).
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'job_descriptions' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_jobdesc_position'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `job_descriptions` ADD CONSTRAINT `fk_jobdesc_position` "
                "FOREIGN KEY (position) REFERENCES positions(title) "
                "ON DELETE CASCADE ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def init_job_descriptions():
    """Create the job_descriptions table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_job_descriptions_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def _split_requirements(value: str | None) -> list[str]:
    return [v for v in (value or "").split(",") if v]


def _job_description_row(row: dict) -> dict:
    row["attachment_requirements"] = _split_requirements(row.get("attachment_requirements"))
    row["published"] = bool(row.get("published"))
    return row


def get_job_description(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_job_descriptions_table(cursor)
    cursor.execute("SELECT * FROM `job_descriptions` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return _job_description_row(row) if row else None


def _job_descriptions_where(search: str, published: bool | None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(position LIKE %s OR description LIKE %s)")
        params += [like, like]
    if published is not None:
        clauses.append("published = %s")
        params.append(1 if published else 0)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def list_job_descriptions(
    search: str = "", published: bool | None = None, limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List job descriptions, optionally filtered by a search term matched
    against position/description and/or published status, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _job_descriptions_where(search, published)
    query = f"SELECT * FROM `job_descriptions` {where} ORDER BY created_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [_job_description_row(r) for r in rows]


def count_job_descriptions(search: str = "", published: bool | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _job_descriptions_where(search, published)
    cursor.execute(f"SELECT COUNT(*) FROM `job_descriptions` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def count_job_descriptions_by_status(search: str = "") -> dict[str, int]:
    return {
        "published": count_job_descriptions(search, published=True),
        "draft":     count_job_descriptions(search, published=False),
    }


def get_published_job_description_for_position(position: str) -> dict | None:
    """Most recently published job description for a position, or None."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `job_descriptions` WHERE position = %s AND published = 1 "
        "ORDER BY created_at DESC LIMIT 1",
        (position,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return _job_description_row(row) if row else None


def create_job_description(
    position: str,
    description: str = "",
    num_applicants_required: int = 1,
    application_deadline=None,
    attachment_requirements: list[str] | None = None,
) -> int:
    """Create a job description (as a draft) and return its new id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `job_descriptions` "
        "(position, description, num_applicants_required, application_deadline, attachment_requirements) "
        "VALUES (%s, %s, %s, %s, %s)",
        (position, description or None, num_applicants_required, application_deadline,
         ",".join(attachment_requirements or [])),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_job_description(
    id: str,
    position: str,
    description: str = "",
    num_applicants_required: int = 1,
    application_deadline=None,
    attachment_requirements: list[str] | None = None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `job_descriptions` SET position=%s, description=%s, num_applicants_required=%s, "
        "application_deadline=%s, attachment_requirements=%s WHERE id=%s",
        (position, description or None, num_applicants_required, application_deadline,
         ",".join(attachment_requirements or []), id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_job_description(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `job_descriptions` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def set_job_description_published(id: str, published: bool) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `job_descriptions` SET published=%s WHERE id=%s",
        (1 if published else 0, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Polling stations (master reference list) ──────────────────────────────────

def init_polling_stations():
    """Create the polling_stations reference table if it doesn't exist yet."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `polling_stations` (
            id                       INT AUTO_INCREMENT PRIMARY KEY,
            county                   VARCHAR(100),
            county_code              VARCHAR(20),
            constituency             VARCHAR(100),
            constituency_code        VARCHAR(20),
            ward                     VARCHAR(100),
            ward_code                VARCHAR(20),
            ward_id                  VARCHAR(4),
            polling_station_code     VARCHAR(50) UNIQUE NOT NULL,
            polling_station_name     VARCHAR(255) NOT NULL,
            registered_voters        INT DEFAULT 0,
            INDEX (county_code),
            INDEX (constituency_code),
            INDEX (ward_code)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    # Add ward_id to tables that pre-date the demography link.
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'polling_stations' AND column_name = 'ward_id'"
    )
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE `polling_stations` ADD COLUMN `ward_id` VARCHAR(4)")

    # Link to the demography reference table (wards table must already exist).
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'polling_stations' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_polling_stations_ward'"
    )
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE `polling_stations` ADD CONSTRAINT `fk_polling_stations_ward` "
            "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) "
            "ON DELETE SET NULL ON UPDATE CASCADE"
        )
    conn.commit()
    cursor.close()
    conn.close()


def list_polling_stations(search: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    """Return a page of polling stations, optionally filtered by a search term
    matched against county/constituency/ward/station name/station code."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE county LIKE %s OR constituency LIKE %s OR ward LIKE %s "
            "OR polling_station_name LIKE %s OR polling_station_code LIKE %s"
        )
        params = (like, like, like, like, like)
    cursor.execute(
        f"SELECT * FROM `polling_stations` {where} "
        "ORDER BY county, constituency, ward, polling_station_code "
        "LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_polling_stations(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE county LIKE %s OR constituency LIKE %s OR ward LIKE %s "
            "OR polling_station_name LIKE %s OR polling_station_code LIKE %s"
        )
        params = (like, like, like, like, like)
    cursor.execute(f"SELECT COUNT(*) FROM `polling_stations` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def get_polling_station(code: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `polling_stations` WHERE polling_station_code = %s", (code,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_polling_station(*, county, county_code, constituency, constituency_code,
                         ward, ward_code, polling_station_code, polling_station_name,
                         registered_voters: int = 0, ward_id: str | None = None) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `polling_stations` "
        "(county, county_code, constituency, constituency_code, ward, ward_code, ward_id, "
        " polling_station_code, polling_station_name, registered_voters) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (county, county_code, constituency, constituency_code, ward, ward_code, ward_id,
         polling_station_code, polling_station_name, registered_voters),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_polling_station(old_code: str, *, county, county_code, constituency, constituency_code,
                            ward, ward_code, polling_station_code, polling_station_name,
                            registered_voters: int = 0, ward_id: str | None = None) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `polling_stations` SET "
        "county = %s, county_code = %s, constituency = %s, constituency_code = %s, "
        "ward = %s, ward_code = %s, ward_id = %s, polling_station_code = %s, "
        "polling_station_name = %s, registered_voters = %s "
        "WHERE polling_station_code = %s",
        (county, county_code, constituency, constituency_code, ward, ward_code, ward_id,
         polling_station_code, polling_station_name, registered_voters, old_code),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_polling_station(code: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `polling_stations` WHERE polling_station_code = %s", (code,))
    conn.commit()
    cursor.close()
    conn.close()


def bulk_upsert_polling_stations(rows: list[dict], skip_existing: bool = False) -> tuple[int, int]:
    """Insert/update many stations in one connection.

    By default, existing station codes are updated in place (re-importing an
    updated register is a common workflow). With skip_existing=True, rows
    whose station code already exists are left untouched (via INSERT IGNORE)
    instead of overwritten — used for large one-off imports where any
    already-loaded stations should be skipped rather than reprocessed.

    Returns (inserted_count, updated_count_or_skipped_count)."""
    rows = [{**r, "ward_id": _pad_ward_id(r["ward_id"]) if r.get("ward_id") else None} for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()

    if skip_existing:
        cursor.executemany(
            "INSERT IGNORE INTO `polling_stations` "
            "(county, county_code, constituency, constituency_code, ward, ward_code, ward_id, "
            " polling_station_code, polling_station_name, registered_voters) "
            "VALUES (%(county)s, %(county_code)s, %(constituency)s, %(constituency_code)s, "
            " %(ward)s, %(ward_code)s, %(ward_id)s, %(polling_station_code)s, %(polling_station_name)s, "
            " %(registered_voters)s)",
            rows,
        )
        conn.commit()
        inserted_count = max(cursor.rowcount, 0)
        cursor.close()
        conn.close()
        return inserted_count, len(rows) - inserted_count

    codes = [r["polling_station_code"] for r in rows]
    existing: set[str] = set()
    for i in range(0, len(codes), 1000):
        batch = codes[i:i + 1000]
        placeholders = ",".join(["%s"] * len(batch))
        cursor.execute(
            f"SELECT polling_station_code FROM `polling_stations` "
            f"WHERE polling_station_code IN ({placeholders})",
            batch,
        )
        existing.update(r[0] for r in cursor.fetchall())

    cursor.executemany(
        "INSERT INTO `polling_stations` "
        "(county, county_code, constituency, constituency_code, ward, ward_code, ward_id, "
        " polling_station_code, polling_station_name, registered_voters) "
        "VALUES (%(county)s, %(county_code)s, %(constituency)s, %(constituency_code)s, "
        " %(ward)s, %(ward_code)s, %(ward_id)s, %(polling_station_code)s, %(polling_station_name)s, "
        " %(registered_voters)s) "
        "ON DUPLICATE KEY UPDATE "
        "county=VALUES(county), county_code=VALUES(county_code), "
        "constituency=VALUES(constituency), constituency_code=VALUES(constituency_code), "
        "ward=VALUES(ward), ward_code=VALUES(ward_code), ward_id=VALUES(ward_id), "
        "polling_station_name=VALUES(polling_station_name), "
        "registered_voters=VALUES(registered_voters)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()

    updated_count = sum(1 for c in codes if c in existing)
    inserted_count = len(rows) - updated_count
    return inserted_count, updated_count


def list_polling_stations_by_codes(codes: list[str]) -> list[dict]:
    """Fetch specific stations by code, regardless of any search filter —
    used to keep already-assigned stations visible in assignment pickers."""
    if not codes:
        return []
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(codes))
    cursor.execute(
        f"SELECT * FROM `polling_stations` WHERE polling_station_code IN ({placeholders})",
        codes,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── User ↔ polling station assignments ─────────────────────────────────────────

def init_user_polling_stations():
    """Create the many-to-many user/polling-station assignment table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `user_polling_stations` (
            username              VARCHAR(100) NOT NULL,
            polling_station_code  VARCHAR(50) NOT NULL,
            PRIMARY KEY (username, polling_station_code)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    conn.commit()
    cursor.close()
    conn.close()


def get_user_polling_station_codes(username: str) -> list[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT polling_station_code FROM `user_polling_stations` WHERE username = %s",
        (username,),
    )
    codes = [r[0] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return codes


def get_user_polling_stations(username: str) -> list[dict]:
    """Full station records assigned to a user, for display."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ps.* FROM `user_polling_stations` ups "
        "JOIN `polling_stations` ps ON ps.polling_station_code = ups.polling_station_code "
        "WHERE ups.username = %s "
        "ORDER BY ps.county, ps.constituency, ps.ward, ps.polling_station_code",
        (username,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_user_polling_stations() -> dict[str, int]:
    """Return {username: assigned_station_count} for every user in one query."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, COUNT(*) FROM `user_polling_stations` GROUP BY username")
    counts = dict(cursor.fetchall())
    cursor.close()
    conn.close()
    return counts


def assign_user_polling_stations(username: str, codes: list[str]) -> None:
    """Replace a user's polling-station assignments with exactly `codes`."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `user_polling_stations` WHERE username = %s", (username,))
    if codes:
        cursor.executemany(
            "INSERT INTO `user_polling_stations` (username, polling_station_code) VALUES (%s, %s)",
            [(username, code) for code in codes],
        )
    conn.commit()
    cursor.close()
    conn.close()


def user_can_access_station(username: str, polling_station_code: str | None) -> bool:
    """Admins may upload for any station. Everyone else needs an explicit
    assignment row — a user with zero assignments is blocked from all uploads."""
    user = get_user(username)
    if user and user.get("role") == "admin":
        return True
    if not polling_station_code:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM `user_polling_stations` WHERE username = %s AND polling_station_code = %s",
        (username, polling_station_code),
    )
    ok = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return ok


# ── User document attachments ───────────────────────────────────────────────────

def init_user_documents():
    """Create the table tracking documents (ID scans, certificates, etc.)
    attached to a user account. Files themselves live under USER_DOCS_DIR."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `user_documents` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            username          VARCHAR(100) NOT NULL,
            title             VARCHAR(200) NOT NULL,
            filename          VARCHAR(512) NOT NULL,
            original_filename VARCHAR(255),
            uploaded_by       VARCHAR(100),
            uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    conn.commit()
    cursor.close()
    conn.close()


def save_user_document_file(username: str, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured; otherwise write uploaded bytes
    under USER_DOCS_DIR/<username>/. Returns either the Cloudinary URL or the
    unique stored filename (safe for the filesystem, collision-free)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/user_documents/{username}", public_id=stored_name)
    if remote_url:
        return remote_url
    user_dir = USER_DOCS_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / stored_name).write_bytes(file_bytes)
    return stored_name


def add_user_document(username: str, title: str, filename: str,
                       original_filename: str, uploaded_by: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `user_documents` (username, title, filename, original_filename, uploaded_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (username, title, filename, original_filename, uploaded_by),
    )
    conn.commit()
    doc_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return doc_id


def list_user_documents(username: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `user_documents` WHERE username = %s ORDER BY uploaded_at DESC",
        (username,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_user_document(doc_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `user_documents` WHERE id = %s", (doc_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_user_document_bytes(doc_id: int) -> tuple[bytes, str] | None:
    """Return (file_bytes, display_filename) for download, or None if missing."""
    doc = get_user_document(doc_id)
    if not doc:
        return None
    display_name = doc["original_filename"] or doc["filename"]
    if cloudinary_storage.is_remote_ref(doc["filename"]):
        data = cloudinary_storage.fetch_bytes(doc["filename"])
        return (data, display_name) if data is not None else None
    path = USER_DOCS_DIR / doc["username"] / doc["filename"]
    if not path.exists():
        return None
    return path.read_bytes(), display_name


def delete_user_document(doc_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT username, filename FROM `user_documents` WHERE id = %s", (doc_id,))
    row = cursor.fetchone()
    if row:
        if cloudinary_storage.is_remote_ref(row["filename"]):
            cloudinary_storage.destroy(row["filename"])
        else:
            (USER_DOCS_DIR / row["username"] / row["filename"]).unlink(missing_ok=True)
    cursor.execute("DELETE FROM `user_documents` WHERE id = %s", (doc_id,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Demography: counties / constituencies / wards ──────────────────────────────
# Official IEBC administrative hierarchy. IDs are the official numeric codes
# (assigned manually, not auto-increment) so they stay stable across imports.
# Codes are stored zero-padded (county/constituency: 3 digits, ward: 4 digits)
# to match IEBC's published numbering (e.g. "001", "045", "290", "0001").

def _pad_code(value, width: int) -> str:
    """Normalize an ID (int, "30", or already-padded "030") to a zero-padded code."""
    return str(int(value)).zfill(width)


def _pad_county_id(value) -> str:
    return _pad_code(value, 3)


def _pad_constituency_id(value) -> str:
    return _pad_code(value, 3)


def _pad_ward_id(value) -> str:
    return _pad_code(value, 4)


def init_demography():
    """Create the counties/constituencies/wards reference tables if missing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `counties` (
            county_id    VARCHAR(3) PRIMARY KEY,
            county_name  VARCHAR(100) NOT NULL
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `constituencies` (
            constituency_id    VARCHAR(3) PRIMARY KEY,
            constituency_name  VARCHAR(100) NOT NULL,
            county_id          VARCHAR(3) NOT NULL,
            FOREIGN KEY (county_id) REFERENCES counties(county_id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            INDEX (county_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `wards` (
            ward_id            VARCHAR(4) PRIMARY KEY,
            ward_name          VARCHAR(100) NOT NULL,
            constituency_id    VARCHAR(3) NOT NULL,
            FOREIGN KEY (constituency_id) REFERENCES constituencies(constituency_id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            INDEX (constituency_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    conn.commit()
    cursor.close()
    conn.close()


# ── Counties ─────────────────────────────────────────────────────────────────

def list_counties(search: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = "WHERE county_name LIKE %s OR county_id LIKE %s"
        params = (like, like)
    cursor.execute(
        f"SELECT co.*, "
        "(SELECT COUNT(*) FROM constituencies c WHERE c.county_id = co.county_id) AS constituency_count "
        f"FROM `counties` co {where} ORDER BY co.county_name LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_counties(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = "WHERE county_name LIKE %s OR county_id LIKE %s"
        params = (like, like)
    cursor.execute(f"SELECT COUNT(*) FROM `counties` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def list_all_counties() -> list[dict]:
    """Unpaginated list for dropdowns."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `counties` ORDER BY county_name")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_county(county_id) -> dict | None:
    county_id = _pad_county_id(county_id)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `counties` WHERE county_id = %s", (county_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_county(county_id, county_name: str) -> None:
    county_id = _pad_county_id(county_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `counties` (county_id, county_name) VALUES (%s, %s)",
        (county_id, county_name),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_county(old_id, county_id, county_name: str) -> None:
    old_id = _pad_county_id(old_id)
    county_id = _pad_county_id(county_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `counties` SET county_id = %s, county_name = %s WHERE county_id = %s",
        (county_id, county_name, old_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_county(county_id) -> None:
    county_id = _pad_county_id(county_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `counties` WHERE county_id = %s", (county_id,))
    conn.commit()
    cursor.close()
    conn.close()


def bulk_upsert_counties(rows: list[dict]) -> tuple[int, int]:
    """rows: [{county_id, county_name}, ...]. Returns (inserted, updated)."""
    rows = [{**r, "county_id": _pad_county_id(r["county_id"])} for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()
    ids = [r["county_id"] for r in rows]
    existing: set[str] = set()
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(f"SELECT county_id FROM `counties` WHERE county_id IN ({placeholders})", ids)
        existing = {r[0] for r in cursor.fetchall()}
    cursor.executemany(
        "INSERT INTO `counties` (county_id, county_name) VALUES (%(county_id)s, %(county_name)s) "
        "ON DUPLICATE KEY UPDATE county_name=VALUES(county_name)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()
    updated_count = sum(1 for i in ids if i in existing)
    return len(rows) - updated_count, updated_count


# ── Constituencies ───────────────────────────────────────────────────────────

def list_constituencies(search: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE c.constituency_name LIKE %s OR co.county_name LIKE %s "
            "OR c.constituency_id LIKE %s"
        )
        params = (like, like, like)
    cursor.execute(
        "SELECT c.*, co.county_name, "
        "(SELECT COUNT(*) FROM wards w WHERE w.constituency_id = c.constituency_id) AS ward_count "
        f"FROM `constituencies` c JOIN `counties` co ON co.county_id = c.county_id {where} "
        "ORDER BY co.county_name, c.constituency_name LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_constituencies(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE c.constituency_name LIKE %s OR co.county_name LIKE %s "
            "OR c.constituency_id LIKE %s"
        )
        params = (like, like, like)
    cursor.execute(
        f"SELECT COUNT(*) FROM `constituencies` c JOIN `counties` co ON co.county_id = c.county_id {where}",
        params,
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def list_all_constituencies() -> list[dict]:
    """Unpaginated list (with county name) for dropdowns."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT c.*, co.county_name FROM `constituencies` c "
        "JOIN `counties` co ON co.county_id = c.county_id "
        "ORDER BY co.county_name, c.constituency_name"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_all_wards() -> list[dict]:
    """Unpaginated list (with constituency/county names) for dropdowns."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT w.*, c.constituency_name, co.county_name FROM `wards` w "
        "JOIN `constituencies` c ON c.constituency_id = w.constituency_id "
        "JOIN `counties` co ON co.county_id = c.county_id "
        "ORDER BY co.county_name, c.constituency_name, w.ward_name"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def find_ward_by_names(county_name: str, constituency_name: str, ward_name: str) -> str | None:
    """Best-effort lookup of a ward_id from (county, constituency, ward) names,
    for opportunistically linking legacy free-text records without forcing a
    manual re-pick. Relies on the tables' case-insensitive collation."""
    if not (county_name and constituency_name and ward_name):
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT w.ward_id FROM `wards` w "
        "JOIN `constituencies` c ON c.constituency_id = w.constituency_id "
        "JOIN `counties` co ON co.county_id = c.county_id "
        "WHERE co.county_name = %s AND c.constituency_name = %s AND w.ward_name = %s",
        (county_name.strip(), constituency_name.strip(), ward_name.strip()),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def find_county_by_name(county_name: str) -> str | None:
    """Best-effort lookup of a county_id from its name."""
    if not county_name:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT county_id FROM `counties` WHERE county_name = %s", (county_name.strip(),))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def find_constituency_by_names(county_name: str, constituency_name: str) -> str | None:
    """Best-effort lookup of a constituency_id from (county, constituency) names."""
    if not (county_name and constituency_name):
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT c.constituency_id FROM `constituencies` c "
        "JOIN `counties` co ON co.county_id = c.county_id "
        "WHERE co.county_name = %s AND c.constituency_name = %s",
        (county_name.strip(), constituency_name.strip()),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def get_constituency(constituency_id) -> dict | None:
    constituency_id = _pad_constituency_id(constituency_id)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `constituencies` WHERE constituency_id = %s", (constituency_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_constituency(constituency_id, constituency_name: str, county_id) -> None:
    constituency_id = _pad_constituency_id(constituency_id)
    county_id = _pad_county_id(county_id)
    constituency_name = constituency_name.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `constituencies` (constituency_id, constituency_name, county_id) "
        "VALUES (%s, %s, %s)",
        (constituency_id, constituency_name, county_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_constituency(old_id, constituency_id, constituency_name: str, county_id) -> None:
    old_id = _pad_constituency_id(old_id)
    constituency_id = _pad_constituency_id(constituency_id)
    county_id = _pad_county_id(county_id)
    constituency_name = constituency_name.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `constituencies` SET constituency_id = %s, constituency_name = %s, county_id = %s "
        "WHERE constituency_id = %s",
        (constituency_id, constituency_name, county_id, old_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_constituency(constituency_id) -> None:
    constituency_id = _pad_constituency_id(constituency_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `constituencies` WHERE constituency_id = %s", (constituency_id,))
    conn.commit()
    cursor.close()
    conn.close()


def bulk_upsert_constituencies(rows: list[dict]) -> tuple[int, int]:
    """rows: [{constituency_id, constituency_name, county_id}, ...]."""
    rows = [{
        **r,
        "constituency_id": _pad_constituency_id(r["constituency_id"]),
        "constituency_name": r["constituency_name"].strip().upper(),
        "county_id": _pad_county_id(r["county_id"]),
    } for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()
    ids = [r["constituency_id"] for r in rows]
    existing: set[str] = set()
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"SELECT constituency_id FROM `constituencies` WHERE constituency_id IN ({placeholders})", ids
        )
        existing = {r[0] for r in cursor.fetchall()}
    cursor.executemany(
        "INSERT INTO `constituencies` (constituency_id, constituency_name, county_id) "
        "VALUES (%(constituency_id)s, %(constituency_name)s, %(county_id)s) "
        "ON DUPLICATE KEY UPDATE constituency_name=VALUES(constituency_name), county_id=VALUES(county_id)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()
    updated_count = sum(1 for i in ids if i in existing)
    return len(rows) - updated_count, updated_count


# ── Wards ────────────────────────────────────────────────────────────────────

def list_wards(search: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE w.ward_name LIKE %s OR c.constituency_name LIKE %s OR co.county_name LIKE %s "
            "OR w.ward_id LIKE %s"
        )
        params = (like, like, like, like)
    cursor.execute(
        "SELECT w.*, c.constituency_name, co.county_name "
        "FROM `wards` w "
        "JOIN `constituencies` c ON c.constituency_id = w.constituency_id "
        "JOIN `counties` co ON co.county_id = c.county_id "
        f"{where} ORDER BY co.county_name, c.constituency_name, w.ward_name LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_wards(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = (
            "WHERE w.ward_name LIKE %s OR c.constituency_name LIKE %s OR co.county_name LIKE %s "
            "OR w.ward_id LIKE %s"
        )
        params = (like, like, like, like)
    cursor.execute(
        "SELECT COUNT(*) FROM `wards` w "
        "JOIN `constituencies` c ON c.constituency_id = w.constituency_id "
        f"JOIN `counties` co ON co.county_id = c.county_id {where}",
        params,
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def get_ward(ward_id) -> dict | None:
    ward_id = _pad_ward_id(ward_id)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `wards` WHERE ward_id = %s", (ward_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_ward(ward_id, ward_name: str, constituency_id) -> None:
    ward_id = _pad_ward_id(ward_id)
    constituency_id = _pad_constituency_id(constituency_id)
    ward_name = ward_name.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `wards` (ward_id, ward_name, constituency_id) VALUES (%s, %s, %s)",
        (ward_id, ward_name, constituency_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_ward(old_id, ward_id, ward_name: str, constituency_id) -> None:
    old_id = _pad_ward_id(old_id)
    ward_id = _pad_ward_id(ward_id)
    constituency_id = _pad_constituency_id(constituency_id)
    ward_name = ward_name.strip().upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `wards` SET ward_id = %s, ward_name = %s, constituency_id = %s WHERE ward_id = %s",
        (ward_id, ward_name, constituency_id, old_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_ward(ward_id) -> None:
    ward_id = _pad_ward_id(ward_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `wards` WHERE ward_id = %s", (ward_id,))
    conn.commit()
    cursor.close()
    conn.close()


def bulk_upsert_wards(rows: list[dict]) -> tuple[int, int]:
    """rows: [{ward_id, ward_name, constituency_id}, ...]."""
    rows = [{
        **r,
        "ward_id": _pad_ward_id(r["ward_id"]),
        "ward_name": r["ward_name"].strip().upper(),
        "constituency_id": _pad_constituency_id(r["constituency_id"]),
    } for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()
    ids = [r["ward_id"] for r in rows]
    existing: set[str] = set()
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(f"SELECT ward_id FROM `wards` WHERE ward_id IN ({placeholders})", ids)
        existing = {r[0] for r in cursor.fetchall()}
    cursor.executemany(
        "INSERT INTO `wards` (ward_id, ward_name, constituency_id) "
        "VALUES (%(ward_id)s, %(ward_name)s, %(constituency_id)s) "
        "ON DUPLICATE KEY UPDATE ward_name=VALUES(ward_name), constituency_id=VALUES(constituency_id)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()
    updated_count = sum(1 for i in ids if i in existing)
    return len(rows) - updated_count, updated_count




# ── Applications ──────────────────────────────────────────────────────────────

APPLICATION_STAGES = ["application", "shortlisting", "interview", "hired", "rejected"]
APPLICATION_STAGE_LABELS = {
    "application":  "Application",
    "shortlisting": "Shortlisting",
    "interview":    "Interview",
    "hired":        "Hired",
    "rejected":     "Rejected",
}
_STAGE_ENUM_SQL = "ENUM({}) DEFAULT 'application'".format(
    ",".join(f"'{s}'" for s in APPLICATION_STAGES)
)


def _ensure_applications_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `applications` (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            surname       VARCHAR(100),
            other_names   VARCHAR(100),
            email         VARCHAR(255),
            position      VARCHAR(100),
            id_passport_number VARCHAR(50),
            phone_number       VARCHAR(30),
            gender             VARCHAR(20),
            date_of_birth      DATE,
            county             VARCHAR(100),
            sub_county         VARCHAR(100),
            ward               VARCHAR(100),
            ward_id            VARCHAR(4),
            stage              {_STAGE_ENUM_SQL},
            qualification_reason VARCHAR(500),
            analyzed_at        TIMESTAMP NULL DEFAULT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("surname",      "VARCHAR(100)"),
        ("other_names", "VARCHAR(100)"),
        ("email",      "VARCHAR(255)"),
        ("position",   "VARCHAR(100)"),
        ("id_passport_number", "VARCHAR(50)"),
        ("phone_number",       "VARCHAR(30)"),
        ("gender",             "VARCHAR(20)"),
        ("date_of_birth",      "DATE"),
        ("county",             "VARCHAR(100)"),
        ("sub_county",         "VARCHAR(100)"),
        ("ward",               "VARCHAR(100)"),
        ("ward_id",            "VARCHAR(4)"),
        ("stage",              _STAGE_ENUM_SQL),
        ("qualification_reason", "VARCHAR(500)"),
        ("analyzed_at",          "TIMESTAMP NULL DEFAULT NULL"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'applications' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `applications` ADD COLUMN `{col}` {definition}")
    # Link to the demography reference table (wards table must already exist).
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'applications' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_applicant_ward'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `applications` ADD CONSTRAINT `fk_applicant_ward` "
                "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) "
                "ON DELETE SET NULL ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # (e.g. the API and Streamlit processes booting at the same time)
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def init_applications():
    """Create an applications table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_applications_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_application(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_applications_table(cursor)
    cursor.execute("SELECT * FROM `applications` WHERE id = %s", (id,))
    application = cursor.fetchone()
    cursor.close()
    conn.close()
    return application


def _applications_where(
    search: str, stage: str | None, positions: list[str] | None = None,
) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(other_names LIKE %s OR surname LIKE %s OR email LIKE %s OR position LIKE %s)")
        params += [like, like, like, like]
    if stage:
        clauses.append("stage = %s")
        params.append(stage)
    if positions:
        placeholders = ",".join(["%s"] * len(positions))
        clauses.append(f"position IN ({placeholders})")
        params += list(positions)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def list_applications(
    search: str = "", limit: int | None = None, offset: int = 0, stage: str | None = None,
    positions: list[str] | None = None,
) -> list[dict]:
    """List applications, optionally filtered by a search term matched against
    name/email/position, a pipeline stage, and/or a set of positions, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _applications_where(search, stage, positions)
    query = (
        "SELECT id, other_names, surname, email, position, stage, "
        "qualification_reason, analyzed_at, created_at "
        f"FROM `applications` {where} ORDER BY created_at"
    )
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    applications = cursor.fetchall()
    cursor.close()
    conn.close()
    return applications


def count_applications(
    search: str = "", stage: str | None = None, positions: list[str] | None = None,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _applications_where(search, stage, positions)
    cursor.execute(f"SELECT COUNT(*) FROM `applications` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def count_applications_by_stage(search: str = "") -> dict[str, int]:
    """Return {stage: count} for every stage that has at least one matching
    application. Stages with no matches are omitted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _applications_where(search, None)
    cursor.execute(f"SELECT stage, COUNT(*) FROM `applications` {where} GROUP BY stage", params)
    counts = {stage: count for stage, count in cursor.fetchall()}
    cursor.close()
    conn.close()
    return counts

def create_application(
    other_names: str = "",
    surname: str = "",
    email: str = "",
    position: str = "",
    id_passport_number: str = "",
    phone_number: str = "",
    gender: str = "",
    date_of_birth=None,
    county: str = "",
    sub_county: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> int:
    """Create an application and return its new id."""
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `applications` (other_names, surname, email, position, "
        "id_passport_number, phone_number, gender, date_of_birth, county, sub_county, ward, ward_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (other_names or None, surname or None, email or None, position or None,
         id_passport_number or None, phone_number or None, gender or None,
         date_of_birth or None, county or None, sub_county or None, ward or None, ward_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_application_profile(
    id: str,
    other_names: str = "",
    surname: str = "",
    email: str = "",
    position: str = "",
    id_passport_number: str = "",
    phone_number: str = "",
    gender: str = "",
    date_of_birth=None,
    county: str = "",
    sub_county: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `applications` SET other_names=%s, surname=%s, email=%s, position=%s, "
        "id_passport_number=%s, phone_number=%s, gender=%s, date_of_birth=%s, "
        "county=%s, sub_county=%s, ward=%s, ward_id=%s WHERE id=%s",
        (other_names or None, surname or None, email or None, position or None,
         id_passport_number or None, phone_number or None, gender or None,
         date_of_birth or None, county or None, sub_county or None, ward or None, ward_id, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_application(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT filename FROM `applicant_documents` WHERE application_id = %s", (id,))
    doc_files = [r["filename"] for r in cursor.fetchall()]
    for fname in doc_files:
        if cloudinary_storage.is_remote_ref(fname):
            cloudinary_storage.destroy(fname)
        else:
            (APPLICANT_DOCS_DIR / str(id) / fname).unlink(missing_ok=True)

    # `applicant_documents` rows are removed automatically via ON DELETE CASCADE.
    cursor.execute("DELETE FROM `applications` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    try:
        (APPLICANT_DOCS_DIR / str(id)).rmdir()
    except OSError:
        pass


def delete_applications(ids: list[str]) -> None:
    if not ids:
        return
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"SELECT application_id, filename FROM `applicant_documents` WHERE application_id IN ({placeholders})",
        tuple(ids),
    )
    for row in cursor.fetchall():
        if cloudinary_storage.is_remote_ref(row["filename"]):
            cloudinary_storage.destroy(row["filename"])
        else:
            (APPLICANT_DOCS_DIR / str(row["application_id"]) / row["filename"]).unlink(missing_ok=True)

    cursor.execute(f"DELETE FROM `applications` WHERE id IN ({placeholders})", tuple(ids))
    conn.commit()
    cursor.close()
    conn.close()
    for id in ids:
        try:
            (APPLICANT_DOCS_DIR / str(id)).rmdir()
        except OSError:
            pass


def update_application_stage(id: str, stage: str) -> None:
    """Move a single application to a different pipeline stage."""
    if stage not in APPLICATION_STAGES:
        raise ValueError(f"Invalid stage: {stage!r}")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE `applications` SET stage=%s WHERE id=%s", (stage, id))
    conn.commit()
    cursor.close()
    conn.close()


def update_applications_stage(ids: list[str], stage: str) -> None:
    """Move a batch of applications to a different pipeline stage."""
    if not ids:
        return
    if stage not in APPLICATION_STAGES:
        raise ValueError(f"Invalid stage: {stage!r}")
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"UPDATE `applications` SET stage=%s WHERE id IN ({placeholders})",
        (stage, *ids),
    )
    conn.commit()
    cursor.close()
    conn.close()


def set_application_qualification_reason(id: str, reason: str | None) -> None:
    """Record the outcome of an automated requirements screening. A NULL
    reason means the applicant qualified (or hasn't been screened yet)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `applications` SET qualification_reason=%s, analyzed_at=NOW() WHERE id=%s",
        (reason[:500] if reason else None, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Party members ─────────────────────────────────────────────────────────────

def _ensure_party_members_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `party_members` (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            name          VARCHAR(150) NOT NULL,
            id_number     VARCHAR(50) NOT NULL,
            email         VARCHAR(255),
            phone_number  VARCHAR(30),
            age           INT,
            gender        VARCHAR(20),
            county        VARCHAR(100),
            constituency  VARCHAR(100),
            ward          VARCHAR(100),
            ward_id       VARCHAR(4),
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_party_member_id_number` (id_number)
        )
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("email",        "VARCHAR(255)"),
        ("phone_number", "VARCHAR(30)"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'party_members' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `party_members` ADD COLUMN `{col}` {definition}")
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'party_members' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_party_member_ward'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `party_members` ADD CONSTRAINT `fk_party_member_ward` "
                "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) "
                "ON DELETE SET NULL ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # (e.g. the API and Streamlit processes booting at the same time)
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def init_party_members():
    """Create the party_members table (depends on wards)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_party_members_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_party_member(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_party_members_table(cursor)
    cursor.execute("SELECT * FROM `party_members` WHERE id = %s", (id,))
    member = cursor.fetchone()
    cursor.close()
    conn.close()
    return member


def _party_members_where(search: str) -> tuple[str, tuple]:
    if not search:
        return "", ()
    like = f"%{search}%"
    return (
        "WHERE (name LIKE %s OR id_number LIKE %s OR email LIKE %s OR phone_number LIKE %s "
        "OR county LIKE %s OR constituency LIKE %s OR ward LIKE %s)",
        (like, like, like, like, like, like, like),
    )


def list_party_members(search: str = "", limit: int | None = None, offset: int = 0) -> list[dict]:
    """List party members, optionally filtered by a search term matched against
    name/ID number/county/constituency/ward, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _party_members_where(search)
    query = f"SELECT * FROM `party_members` {where} ORDER BY created_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    members = cursor.fetchall()
    cursor.close()
    conn.close()
    return members


def count_party_members(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _party_members_where(search)
    cursor.execute(f"SELECT COUNT(*) FROM `party_members` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def create_party_member(
    name: str,
    id_number: str,
    email: str = "",
    phone_number: str = "",
    age: int | None = None,
    gender: str = "",
    county: str = "",
    constituency: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> int:
    """Create a party member and return its new id."""
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `party_members` (name, id_number, email, phone_number, age, gender, "
        "county, constituency, ward, ward_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (name, id_number, email or None, phone_number or None, age or None, gender or None,
         county or None, constituency or None, ward or None, ward_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_party_member(
    id: str,
    name: str,
    id_number: str,
    email: str = "",
    phone_number: str = "",
    age: int | None = None,
    gender: str = "",
    county: str = "",
    constituency: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `party_members` SET name=%s, id_number=%s, email=%s, phone_number=%s, age=%s, gender=%s, "
        "county=%s, constituency=%s, ward=%s, ward_id=%s WHERE id=%s",
        (name, id_number, email or None, phone_number or None, age or None, gender or None,
         county or None, constituency or None, ward or None, ward_id, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_party_member(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `party_members` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def bulk_upsert_party_members(rows: list[dict]) -> tuple[int, int]:
    """rows: [{name, id_number, email, phone_number, age, gender, county, constituency, ward, ward_id}, ...].
    Existing members are matched (and updated) by id_number."""
    rows = [{**r, "ward_id": _pad_ward_id(r["ward_id"]) if r.get("ward_id") else None} for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_party_members_table(cursor)
    id_numbers = [r["id_number"] for r in rows]
    existing: set[str] = set()
    if id_numbers:
        placeholders = ",".join(["%s"] * len(id_numbers))
        cursor.execute(
            f"SELECT id_number FROM `party_members` WHERE id_number IN ({placeholders})", id_numbers,
        )
        existing = {r[0] for r in cursor.fetchall()}
    cursor.executemany(
        "INSERT INTO `party_members` (name, id_number, email, phone_number, age, gender, "
        "county, constituency, ward, ward_id) "
        "VALUES (%(name)s, %(id_number)s, %(email)s, %(phone_number)s, %(age)s, %(gender)s, "
        "%(county)s, %(constituency)s, %(ward)s, %(ward_id)s) "
        "ON DUPLICATE KEY UPDATE name=VALUES(name), email=VALUES(email), phone_number=VALUES(phone_number), "
        "age=VALUES(age), gender=VALUES(gender), "
        "county=VALUES(county), constituency=VALUES(constituency), ward=VALUES(ward), ward_id=VALUES(ward_id)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()
    updated_count = sum(1 for i in id_numbers if i in existing)
    return len(rows) - updated_count, updated_count


# ── Parties ──────────────────────────────────────────────────────────────────

def _ensure_parties_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `parties` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            name       VARCHAR(150) UNIQUE NOT NULL,
            logo       VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def init_parties():
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_parties_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_party(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `parties` WHERE id = %s", (id,))
    party = cursor.fetchone()
    cursor.close()
    conn.close()
    return party


def _parties_where(search: str) -> tuple[str, tuple]:
    if not search:
        return "", ()
    like = f"%{search}%"
    return "WHERE name LIKE %s", (like,)


def list_parties(search: str = "", limit: int | None = None, offset: int = 0) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _parties_where(search)
    query = f"SELECT * FROM `parties` {where} ORDER BY name"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_parties(search: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _parties_where(search)
    cursor.execute(f"SELECT COUNT(*) FROM `parties` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def create_party(name: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO `parties` (name) VALUES (%s)", (name,))
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_party(id: str, name: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE `parties` SET name = %s WHERE id = %s", (name, id))
    conn.commit()
    cursor.close()
    conn.close()


def delete_party(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT logo FROM `parties` WHERE id = %s", (id,))
    row = cursor.fetchone()
    old_logo = row["logo"] if row else None
    cursor.execute("DELETE FROM `parties` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    if old_logo and cloudinary_storage.is_remote_ref(old_logo):
        cloudinary_storage.destroy(old_logo)
    logo_dir = PARTY_LOGOS_DIR / str(id)
    for f in logo_dir.glob("*"):
        f.unlink(missing_ok=True)
    try:
        logo_dir.rmdir()
    except OSError:
        pass


def bulk_upsert_parties(names: list[str]) -> tuple[int, int]:
    """names: [party name, ...]. Existing parties are matched (kept unchanged
    besides name) by name; logos are never touched by bulk import."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_parties_table(cursor)
    existing: set[str] = set()
    if names:
        placeholders = ",".join(["%s"] * len(names))
        cursor.execute(f"SELECT name FROM `parties` WHERE name IN ({placeholders})", names)
        existing = {r[0] for r in cursor.fetchall()}
    new_names = [n for n in names if n not in existing]
    if new_names:
        cursor.executemany("INSERT INTO `parties` (name) VALUES (%s)", [(n,) for n in new_names])
    conn.commit()
    cursor.close()
    conn.close()
    return len(new_names), len(names) - len(new_names)


def set_party_logo(party_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured, otherwise write the new logo under
    PARTY_LOGOS_DIR/<party_id>/. Points parties.logo at it and deletes the
    previous logo (from Cloudinary or disk, whichever it was on)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    party_dir = PARTY_LOGOS_DIR / str(party_id)
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/party_logos/{party_id}", public_id=stored_name)
    if remote_url:
        stored_value = remote_url
    else:
        party_dir.mkdir(parents=True, exist_ok=True)
        (party_dir / stored_name).write_bytes(file_bytes)
        stored_value = stored_name

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT logo FROM `parties` WHERE id = %s", (party_id,))
    row = cursor.fetchone()
    old_logo = row["logo"] if row else None
    cursor.execute("UPDATE `parties` SET logo=%s WHERE id=%s", (stored_value, party_id))
    conn.commit()
    cursor.close()
    conn.close()

    if old_logo and old_logo != stored_value:
        if cloudinary_storage.is_remote_ref(old_logo):
            cloudinary_storage.destroy(old_logo)
        else:
            (party_dir / old_logo).unlink(missing_ok=True)
    return stored_value


def remove_party_logo(party_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT logo FROM `parties` WHERE id = %s", (party_id,))
    row = cursor.fetchone()
    old_logo = row["logo"] if row else None
    cursor.execute("UPDATE `parties` SET logo=NULL WHERE id=%s", (party_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if old_logo:
        if cloudinary_storage.is_remote_ref(old_logo):
            cloudinary_storage.destroy(old_logo)
        else:
            (PARTY_LOGOS_DIR / str(party_id) / old_logo).unlink(missing_ok=True)


def get_party_logo_bytes(party_id) -> tuple[bytes, str] | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT logo FROM `parties` WHERE id = %s", (party_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row or not row["logo"]:
        return None
    if cloudinary_storage.is_remote_ref(row["logo"]):
        data = cloudinary_storage.fetch_bytes(row["logo"])
        return (data, row["logo"]) if data is not None else None
    path = PARTY_LOGOS_DIR / str(party_id) / row["logo"]
    if not path.exists():
        return None
    return path.read_bytes(), row["logo"]


# ── Candidates ───────────────────────────────────────────────────────────────

# Elective offices, matching the labels used by the IEBC form-type registry
# (form_types.FORM_TYPE_MAP) so candidate positions line up with tally forms.
CANDIDATE_POSITIONS = [
    "President", "County Governor", "Senator", "County Woman Rep",
    "Member of National Assembly", "Member of County Assembly",
]


def _ensure_candidates_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `candidates` (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            name             VARCHAR(150) NOT NULL,
            party_id         INT,
            position         VARCHAR(100),
            candidate_number VARCHAR(20),
            county           VARCHAR(100),
            constituency     VARCHAR(100),
            ward             VARCHAR(100),
            ward_id          VARCHAR(4),
            photo            VARCHAR(255),
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_candidate_name_position` (name, position)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_candidate_party",
         "ALTER TABLE `candidates` ADD CONSTRAINT `fk_candidate_party` "
         "FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE SET NULL ON UPDATE CASCADE"),
        ("fk_candidate_ward",
         "ALTER TABLE `candidates` ADD CONSTRAINT `fk_candidate_ward` "
         "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) ON DELETE SET NULL ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'candidates' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_candidates():
    """Create the candidates table (depends on parties + wards)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_candidates_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_candidate(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT c.*, p.name AS party_name, p.logo AS party_logo FROM `candidates` c "
        "LEFT JOIN `parties` p ON p.id = c.party_id WHERE c.id = %s",
        (id,),
    )
    candidate = cursor.fetchone()
    cursor.close()
    conn.close()
    return candidate


def _candidates_where(search: str, party_id: str | None, position: str | None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append(
            "(c.name LIKE %s OR c.county LIKE %s OR c.constituency LIKE %s OR c.ward LIKE %s)"
        )
        params += [like, like, like, like]
    if party_id:
        clauses.append("c.party_id = %s")
        params.append(party_id)
    if position:
        clauses.append("c.position = %s")
        params.append(position)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, tuple(params)


def list_candidates(
    search: str = "", party_id: str | None = None, position: str | None = None,
    limit: int | None = None, offset: int = 0,
) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _candidates_where(search, party_id, position)
    query = (
        "SELECT c.*, p.name AS party_name, p.logo AS party_logo FROM `candidates` c "
        f"LEFT JOIN `parties` p ON p.id = c.party_id {where} ORDER BY c.name"
    )
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_candidates(search: str = "", party_id: str | None = None, position: str | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _candidates_where(search, party_id, position)
    cursor.execute(f"SELECT COUNT(*) FROM `candidates` c {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def create_candidate(
    name: str,
    party_id: int | None = None,
    position: str = "",
    candidate_number: str = "",
    county: str = "",
    constituency: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> int:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `candidates` (name, party_id, position, candidate_number, "
        "county, constituency, ward, ward_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (name, party_id or None, position or None, candidate_number or None,
         county or None, constituency or None, ward or None, ward_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_candidate(
    id: str,
    name: str,
    party_id: int | None = None,
    position: str = "",
    candidate_number: str = "",
    county: str = "",
    constituency: str = "",
    ward: str = "",
    ward_id: str | None = None,
) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `candidates` SET name=%s, party_id=%s, position=%s, candidate_number=%s, "
        "county=%s, constituency=%s, ward=%s, ward_id=%s WHERE id=%s",
        (name, party_id or None, position or None, candidate_number or None,
         county or None, constituency or None, ward or None, ward_id, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_candidate(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT photo FROM `candidates` WHERE id = %s", (id,))
    row = cursor.fetchone()
    old_photo = row["photo"] if row else None
    cursor.execute("DELETE FROM `candidates` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    if old_photo and cloudinary_storage.is_remote_ref(old_photo):
        cloudinary_storage.destroy(old_photo)
    photo_dir = CANDIDATE_PHOTOS_DIR / str(id)
    for f in photo_dir.glob("*"):
        f.unlink(missing_ok=True)
    try:
        photo_dir.rmdir()
    except OSError:
        pass


def bulk_upsert_candidates(rows: list[dict]) -> tuple[int, int]:
    """rows: [{name, party_id, position, candidate_number, county, constituency,
    ward, ward_id}, ...]. Existing candidates are matched (and updated) by
    (name, position)."""
    rows = [{**r, "ward_id": _pad_ward_id(r["ward_id"]) if r.get("ward_id") else None} for r in rows]
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_candidates_table(cursor)
    keys = [(r["name"], r["position"]) for r in rows]
    existing: set[tuple] = set()
    if keys:
        placeholders = ",".join(["(%s,%s)"] * len(keys))
        cursor.execute(
            f"SELECT name, position FROM `candidates` WHERE (name, position) IN ({placeholders})",
            [v for pair in keys for v in pair],
        )
        existing = {(r[0], r[1]) for r in cursor.fetchall()}
    cursor.executemany(
        "INSERT INTO `candidates` (name, party_id, position, candidate_number, "
        "county, constituency, ward, ward_id) "
        "VALUES (%(name)s, %(party_id)s, %(position)s, %(candidate_number)s, "
        "%(county)s, %(constituency)s, %(ward)s, %(ward_id)s) "
        "ON DUPLICATE KEY UPDATE party_id=VALUES(party_id), candidate_number=VALUES(candidate_number), "
        "county=VALUES(county), constituency=VALUES(constituency), ward=VALUES(ward), ward_id=VALUES(ward_id)",
        rows,
    )
    conn.commit()
    cursor.close()
    conn.close()
    updated_count = sum(1 for k in keys if k in existing)
    return len(rows) - updated_count, updated_count


def set_candidate_photo(candidate_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured, otherwise write the new photo
    under CANDIDATE_PHOTOS_DIR/<candidate_id>/. Points candidates.photo at it
    and deletes the previous photo (from Cloudinary or disk, whichever it
    was on)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    cand_dir = CANDIDATE_PHOTOS_DIR / str(candidate_id)
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/candidate_photos/{candidate_id}", public_id=stored_name)
    if remote_url:
        stored_value = remote_url
    else:
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / stored_name).write_bytes(file_bytes)
        stored_value = stored_name

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT photo FROM `candidates` WHERE id = %s", (candidate_id,))
    row = cursor.fetchone()
    old_photo = row["photo"] if row else None
    cursor.execute("UPDATE `candidates` SET photo=%s WHERE id=%s", (stored_value, candidate_id))
    conn.commit()
    cursor.close()
    conn.close()

    if old_photo and old_photo != stored_value:
        if cloudinary_storage.is_remote_ref(old_photo):
            cloudinary_storage.destroy(old_photo)
        else:
            (cand_dir / old_photo).unlink(missing_ok=True)
    return stored_value


def remove_candidate_photo(candidate_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT photo FROM `candidates` WHERE id = %s", (candidate_id,))
    row = cursor.fetchone()
    old_photo = row["photo"] if row else None
    cursor.execute("UPDATE `candidates` SET photo=NULL WHERE id=%s", (candidate_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if old_photo:
        if cloudinary_storage.is_remote_ref(old_photo):
            cloudinary_storage.destroy(old_photo)
        else:
            (CANDIDATE_PHOTOS_DIR / str(candidate_id) / old_photo).unlink(missing_ok=True)


def get_candidate_photo_bytes(candidate_id) -> tuple[bytes, str] | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT photo FROM `candidates` WHERE id = %s", (candidate_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row or not row["photo"]:
        return None
    if cloudinary_storage.is_remote_ref(row["photo"]):
        data = cloudinary_storage.fetch_bytes(row["photo"])
        return (data, row["photo"]) if data is not None else None
    path = CANDIDATE_PHOTOS_DIR / str(candidate_id) / row["photo"]
    if not path.exists():
        return None
    return path.read_bytes(), row["photo"]


# ── Opinion Polls ────────────────────────────────────────────────────────────
# Two flavours share the same title/breakdown shape: 'pollster' (admin types in
# a third-party firm's reported percentages) and 'self_hosted' (we ask the
# public to vote via the outward-facing site; percentage is then computed live
# from opinion_poll_results.vote_count instead of being admin-entered).

OPINION_POLL_SOURCES = ("pollster", "self_hosted")


def _ensure_opinion_polls_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `opinion_polls` (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            title            VARCHAR(255) NOT NULL,
            position         VARCHAR(100),
            pollster         VARCHAR(150),
            sample_size      INT,
            margin_of_error  DECIMAL(4,2),
            date_conducted   DATE,
            methodology      TEXT,
            source_url       VARCHAR(500),
            notes            TEXT,
            published        TINYINT(1) NOT NULL DEFAULT 0,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    # Add new columns to existing tables that pre-date self-hosted polls
    for col, definition in [
        ("source", "VARCHAR(20) NOT NULL DEFAULT 'pollster'"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'opinion_polls' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `opinion_polls` ADD COLUMN `{col}` {definition}")


def _ensure_opinion_poll_results_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `opinion_poll_results` (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            poll_id        INT NOT NULL,
            candidate_id   INT,
            candidate_name VARCHAR(150) NOT NULL,
            party_id       INT,
            percentage     DECIMAL(5,2) NOT NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for col, definition in [
        ("vote_count", "INT NOT NULL DEFAULT 0"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'opinion_poll_results' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `opinion_poll_results` ADD COLUMN `{col}` {definition}")
    for fk_name, ddl in [
        ("fk_pollresult_poll",
         "ALTER TABLE `opinion_poll_results` ADD CONSTRAINT `fk_pollresult_poll` "
         "FOREIGN KEY (poll_id) REFERENCES opinion_polls(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_pollresult_candidate",
         "ALTER TABLE `opinion_poll_results` ADD CONSTRAINT `fk_pollresult_candidate` "
         "FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE SET NULL ON UPDATE CASCADE"),
        ("fk_pollresult_party",
         "ALTER TABLE `opinion_poll_results` ADD CONSTRAINT `fk_pollresult_party` "
         "FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE SET NULL ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'opinion_poll_results' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def _ensure_opinion_poll_votes_table(cursor):
    """One row per (poll, voter) — the unique key is the actual duplicate-vote
    guard; voter_hash is a salted hash of the caller's IP (see api.py), never
    the raw IP, so this table isn't itself a store of personal data."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `opinion_poll_votes` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            poll_id    INT NOT NULL,
            result_id  INT NOT NULL,
            voter_hash CHAR(64) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_poll_voter` (poll_id, voter_hash)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_pollvote_poll",
         "ALTER TABLE `opinion_poll_votes` ADD CONSTRAINT `fk_pollvote_poll` "
         "FOREIGN KEY (poll_id) REFERENCES opinion_polls(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_pollvote_result",
         "ALTER TABLE `opinion_poll_votes` ADD CONSTRAINT `fk_pollvote_result` "
         "FOREIGN KEY (result_id) REFERENCES opinion_poll_results(id) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'opinion_poll_votes' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_opinion_polls():
    """Create the opinion_polls + opinion_poll_results + opinion_poll_votes
    tables (depends on candidates/parties)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_opinion_polls_table(cursor)
    _ensure_opinion_poll_results_table(cursor)
    _ensure_opinion_poll_votes_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def _opinion_poll_row(row: dict) -> dict:
    row["published"] = bool(row.get("published"))
    return row


def get_opinion_poll(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `opinion_polls` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return _opinion_poll_row(row) if row else None


def _opinion_polls_where(search: str, position: str | None, published: bool | None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(title LIKE %s OR pollster LIKE %s)")
        params += [like, like]
    if position:
        clauses.append("position = %s")
        params.append(position)
    if published is not None:
        clauses.append("published = %s")
        params.append(1 if published else 0)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def list_opinion_polls(
    search: str = "", position: str | None = None, published: bool | None = None,
    limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List opinion polls, optionally filtered by a search term matched against
    title/pollster, an elective office, and/or publish state, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _opinion_polls_where(search, position, published)
    query = f"SELECT * FROM `opinion_polls` {where} ORDER BY date_conducted DESC, created_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [_opinion_poll_row(r) for r in rows]


def count_opinion_polls(search: str = "", position: str | None = None, published: bool | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _opinion_polls_where(search, position, published)
    cursor.execute(f"SELECT COUNT(*) FROM `opinion_polls` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def count_opinion_polls_by_publish_state(search: str = "") -> dict[str, int]:
    return {
        "published": count_opinion_polls(search, published=True),
        "draft":     count_opinion_polls(search, published=False),
    }


def list_opinion_poll_results(poll_id: str) -> list[dict]:
    """Per-candidate breakdown for a poll, joined with party name/logo for
    display. For self-hosted polls, `percentage` is computed live from
    vote_count — the stored column is only meaningful for 'pollster' polls,
    where it holds the admin-entered figure."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT r.*, p.name AS party_name, p.logo AS party_logo, o.source AS poll_source "
        "FROM `opinion_poll_results` r "
        "JOIN `opinion_polls` o ON o.id = r.poll_id "
        "LEFT JOIN `parties` p ON p.id = r.party_id "
        "WHERE r.poll_id = %s",
        (poll_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if rows and rows[0]["poll_source"] == "self_hosted":
        total_votes = sum(r["vote_count"] for r in rows)
        for r in rows:
            r["percentage"] = round(r["vote_count"] / total_votes * 100, 2) if total_votes else 0.0
    for r in rows:
        r.pop("poll_source", None)
    rows.sort(key=lambda r: r["percentage"], reverse=True)
    return rows


def _replace_opinion_poll_results(cursor, poll_id, results: list[dict]) -> None:
    """Upserts a poll's candidate/party breakdown. Rows carrying an existing
    `id` are updated in place (leaving vote_count untouched, so editing a
    self-hosted poll's metadata doesn't wipe out votes already cast); rows
    without one are inserted fresh; any existing row no longer present is
    removed."""
    cursor.execute("SELECT id FROM `opinion_poll_results` WHERE poll_id = %s", (poll_id,))
    existing_ids = {r[0] for r in cursor.fetchall()}
    kept_ids = set()

    for r in results:
        result_id = r.get("id")
        if result_id and result_id in existing_ids:
            cursor.execute(
                "UPDATE `opinion_poll_results` SET candidate_id=%s, candidate_name=%s, "
                "party_id=%s, percentage=%s WHERE id=%s",
                (r.get("candidate_id") or None, r["candidate_name"], r.get("party_id") or None,
                 r.get("percentage") or 0, result_id),
            )
            kept_ids.add(result_id)
        else:
            cursor.execute(
                "INSERT INTO `opinion_poll_results` "
                "(poll_id, candidate_id, candidate_name, party_id, percentage) "
                "VALUES (%s, %s, %s, %s, %s)",
                (poll_id, r.get("candidate_id") or None, r["candidate_name"], r.get("party_id") or None,
                 r.get("percentage") or 0),
            )

    removed_ids = existing_ids - kept_ids
    if removed_ids:
        placeholders = ",".join(["%s"] * len(removed_ids))
        cursor.execute(
            f"DELETE FROM `opinion_poll_results` WHERE id IN ({placeholders})",
            tuple(removed_ids),
        )


def create_opinion_poll(
    *, title: str, position: str = "", pollster: str = "", sample_size: int | None = None,
    margin_of_error: float | None = None, date_conducted=None, methodology: str = "",
    source_url: str = "", notes: str = "", source: str = "pollster",
    results: list[dict] | None = None,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `opinion_polls` "
        "(title, position, pollster, sample_size, margin_of_error, date_conducted, "
        " methodology, source_url, notes, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (title, position or None, pollster or None, sample_size, margin_of_error,
         date_conducted, methodology or None, source_url or None, notes or None, source),
    )
    new_id = cursor.lastrowid
    _replace_opinion_poll_results(cursor, new_id, results or [])
    conn.commit()
    cursor.close()
    conn.close()
    return new_id


def update_opinion_poll(
    id: str, *, title: str, position: str = "", pollster: str = "", sample_size: int | None = None,
    margin_of_error: float | None = None, date_conducted=None, methodology: str = "",
    source_url: str = "", notes: str = "", source: str = "pollster",
    results: list[dict] | None = None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `opinion_polls` SET title=%s, position=%s, pollster=%s, sample_size=%s, "
        "margin_of_error=%s, date_conducted=%s, methodology=%s, source_url=%s, notes=%s, source=%s "
        "WHERE id=%s",
        (title, position or None, pollster or None, sample_size, margin_of_error,
         date_conducted, methodology or None, source_url or None, notes or None, source, id),
    )
    if results is not None:
        _replace_opinion_poll_results(cursor, id, results)
    conn.commit()
    cursor.close()
    conn.close()


def cast_opinion_poll_vote(poll_id: str, result_id: int, voter_hash: str) -> None:
    """Records one public vote for a self-hosted poll option. Raises
    ValueError if result_id doesn't belong to poll_id, or lets a
    mysql.connector.Error ('Duplicate entry' on uq_poll_voter) propagate if
    this voter already voted in this poll — callers should treat that
    specific case as 'already voted', not a server error."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM `opinion_poll_results` WHERE id = %s AND poll_id = %s",
            (result_id, poll_id),
        )
        if not cursor.fetchone():
            raise ValueError("Invalid option for this poll.")
        cursor.execute(
            "INSERT INTO `opinion_poll_votes` (poll_id, result_id, voter_hash) VALUES (%s, %s, %s)",
            (poll_id, result_id, voter_hash),
        )
        cursor.execute(
            "UPDATE `opinion_poll_results` SET vote_count = vote_count + 1 WHERE id = %s",
            (result_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def delete_opinion_poll(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `opinion_polls` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def set_opinion_poll_published(id: str, published: bool) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `opinion_polls` SET published=%s WHERE id=%s",
        (1 if published else 0, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Contributions (campaign fundraising via M-Pesa STK push / PayPal) ───────

CONTRIBUTION_METHODS = ("mpesa", "paypal")
CONTRIBUTION_STATUSES = ("pending", "completed", "failed", "cancelled")


def _ensure_contributions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `contributions` (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            contributor_name     VARCHAR(150) NOT NULL,
            phone_number         VARCHAR(30),
            email                VARCHAR(255),
            amount               DECIMAL(12,2) NOT NULL,
            currency             VARCHAR(10) NOT NULL DEFAULT 'KES',
            payment_method       ENUM('mpesa','paypal') NOT NULL,
            status               ENUM('pending','completed','failed','cancelled') NOT NULL DEFAULT 'pending',
            merchant_request_id  VARCHAR(100),
            checkout_request_id  VARCHAR(100),
            mpesa_receipt_number VARCHAR(50),
            paypal_order_id      VARCHAR(100),
            result_desc          VARCHAR(255),
            recorded_by          VARCHAR(100),
            created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX (checkout_request_id),
            INDEX (paypal_order_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def init_contributions():
    """Create the contributions table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_contributions_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def create_contribution(
    contributor_name: str,
    amount: float,
    currency: str,
    payment_method: str,
    phone_number: str = "",
    email: str = "",
    recorded_by: str = "",
) -> int:
    """Record a new contribution attempt (status starts as 'pending') and return its id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_contributions_table(cursor)
    cursor.execute(
        "INSERT INTO `contributions` "
        "(contributor_name, phone_number, email, amount, currency, payment_method, recorded_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (contributor_name, phone_number or None, email or None, amount, currency,
         payment_method, recorded_by or None),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def get_contribution(id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `contributions` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_contribution_by_checkout_request_id(checkout_request_id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `contributions` WHERE checkout_request_id = %s", (checkout_request_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_contribution_by_paypal_order_id(paypal_order_id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `contributions` WHERE paypal_order_id = %s", (paypal_order_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def set_contribution_mpesa_request(id, merchant_request_id: str, checkout_request_id: str) -> None:
    """Attach Safaricom's request identifiers once STK push has been initiated,
    so the later callback (matched by checkout_request_id) can find this row."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `contributions` SET merchant_request_id = %s, checkout_request_id = %s WHERE id = %s",
        (merchant_request_id, checkout_request_id, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def set_contribution_paypal_order(id, paypal_order_id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `contributions` SET paypal_order_id = %s WHERE id = %s", (paypal_order_id, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_contribution_status(
    id, status: str, mpesa_receipt_number: str = "", result_desc: str = "",
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `contributions` SET status = %s, "
        "mpesa_receipt_number = COALESCE(%s, mpesa_receipt_number), "
        "result_desc = %s WHERE id = %s",
        (status, mpesa_receipt_number or None, result_desc or None, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def _contributions_where(search: str, status: str | None, payment_method: str | None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(contributor_name LIKE %s OR phone_number LIKE %s OR email LIKE %s)")
        params += [like, like, like]
    if status:
        clauses.append("status = %s")
        params.append(status)
    if payment_method:
        clauses.append("payment_method = %s")
        params.append(payment_method)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, tuple(params)


def list_contributions(
    search: str = "", status: str | None = None, payment_method: str | None = None,
    limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List contributions, newest first, optionally filtered by search/status/payment_method."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_contributions_table(cursor)
    where, params = _contributions_where(search, status, payment_method)
    query = f"SELECT * FROM `contributions` {where} ORDER BY created_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_contributions(search: str = "", status: str | None = None, payment_method: str | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_contributions_table(cursor)
    where, params = _contributions_where(search, status, payment_method)
    cursor.execute(f"SELECT COUNT(*) FROM `contributions` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def sum_completed_contributions() -> list[dict]:
    """Total raised per currency, completed contributions only —
    kept separate since KES (M-Pesa) and USD (PayPal) can't be added together."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT currency, SUM(amount) AS total, COUNT(*) AS n "
        "FROM `contributions` WHERE status = 'completed' GROUP BY currency"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── Applicant documents (attachments on an application) ─────────────────────

def init_applicant_documents():
    """Create the table tracking documents (CVs, ID scans, certificates, etc.)
    attached to an application. Files themselves live under APPLICANT_DOCS_DIR."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `applicant_documents` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            application_id    INT NOT NULL,
            title             VARCHAR(200) NOT NULL,
            filename          VARCHAR(512) NOT NULL,
            original_filename VARCHAR(255),
            uploaded_by       VARCHAR(100),
            uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (application_id),
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    conn.commit()
    cursor.close()
    conn.close()


def save_applicant_document_file(application_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured; otherwise write uploaded bytes
    under APPLICANT_DOCS_DIR/<application_id>/. Returns either the Cloudinary
    URL or the unique stored filename (safe for the filesystem, collision-free)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    remote_url = cloudinary_storage.upload(
        file_bytes, folder=f"razetally/applicant_documents/{application_id}", public_id=stored_name,
    )
    if remote_url:
        return remote_url
    app_dir = APPLICANT_DOCS_DIR / str(application_id)
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / stored_name).write_bytes(file_bytes)
    return stored_name


def add_applicant_document(application_id, title: str, filename: str,
                            original_filename: str, uploaded_by: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `applicant_documents` (application_id, title, filename, original_filename, uploaded_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (application_id, title, filename, original_filename, uploaded_by),
    )
    conn.commit()
    doc_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return doc_id


def list_applicant_documents(application_id) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `applicant_documents` WHERE application_id = %s ORDER BY uploaded_at DESC",
        (application_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_applicant_documents_for(application_ids: list[str]) -> dict[str, int]:
    """Bulk {application_id: attachment count} for a set of applications, to
    avoid one query per row when listing applications."""
    if not application_ids:
        return {}
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["%s"] * len(application_ids))
    cursor.execute(
        f"SELECT application_id, COUNT(*) FROM `applicant_documents` "
        f"WHERE application_id IN ({placeholders}) GROUP BY application_id",
        tuple(application_ids),
    )
    counts = {str(app_id): count for app_id, count in cursor.fetchall()}
    cursor.close()
    conn.close()
    return counts


def get_applicant_document(doc_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `applicant_documents` WHERE id = %s", (doc_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_applicant_document_bytes(doc_id: int) -> tuple[bytes, str] | None:
    """Return (file_bytes, display_filename) for download, or None if missing."""
    doc = get_applicant_document(doc_id)
    if not doc:
        return None
    display_name = doc["original_filename"] or doc["filename"]
    if cloudinary_storage.is_remote_ref(doc["filename"]):
        data = cloudinary_storage.fetch_bytes(doc["filename"])
        return (data, display_name) if data is not None else None
    path = APPLICANT_DOCS_DIR / str(doc["application_id"]) / doc["filename"]
    if not path.exists():
        return None
    return path.read_bytes(), display_name


def delete_applicant_document(doc_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT application_id, filename FROM `applicant_documents` WHERE id = %s", (doc_id,))
    row = cursor.fetchone()
    if row:
        if cloudinary_storage.is_remote_ref(row["filename"]):
            cloudinary_storage.destroy(row["filename"])
        else:
            (APPLICANT_DOCS_DIR / str(row["application_id"]) / row["filename"]).unlink(missing_ok=True)
    cursor.execute("DELETE FROM `applicant_documents` WHERE id = %s", (doc_id,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Interview questions (a bank of questions per position) ──────────────────

INTERVIEW_QUESTION_TYPES = ["oral", "written"]
_QUESTION_TYPE_ENUM_SQL = "ENUM({}) DEFAULT 'oral'".format(
    ",".join(f"'{t}'" for t in INTERVIEW_QUESTION_TYPES)
)


def _ensure_interview_questions_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `interview_questions` (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            position      VARCHAR(200) NOT NULL,
            question      TEXT NOT NULL,
            question_type {_QUESTION_TYPE_ENUM_SQL},
            sort_order    INT DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add new columns to existing tables that pre-date this schema
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'interview_questions' AND column_name = 'question_type'",
    )
    if not cursor.fetchone():
        cursor.execute(f"ALTER TABLE `interview_questions` ADD COLUMN `question_type` {_QUESTION_TYPE_ENUM_SQL}")

    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'interview_questions' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_interviewq_position'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `interview_questions` ADD CONSTRAINT `fk_interviewq_position` "
                "FOREIGN KEY (position) REFERENCES positions(title) "
                "ON DELETE CASCADE ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def init_interview_questions():
    """Create the interview_questions table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_interview_questions_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_interview_question(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_interview_questions_table(cursor)
    cursor.execute("SELECT * FROM `interview_questions` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def _interview_questions_where(search: str, position: str | None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(position LIKE %s OR question LIKE %s)")
        params += [like, like]
    if position:
        clauses.append("position = %s")
        params.append(position)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def list_interview_questions(
    search: str = "", position: str | None = None, limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List interview questions, optionally filtered by a search term matched
    against position/question and/or a specific position, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _interview_questions_where(search, position)
    query = f"SELECT * FROM `interview_questions` {where} ORDER BY position, sort_order, id"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_interview_questions(search: str = "", position: str | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _interview_questions_where(search, position)
    cursor.execute(f"SELECT COUNT(*) FROM `interview_questions` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def list_interview_questions_for_position(position: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `interview_questions` WHERE position = %s ORDER BY sort_order, id",
        (position,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def create_interview_question(position: str, question: str, question_type: str = "oral") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `interview_questions` (position, question, question_type, sort_order) "
        "VALUES (%s, %s, %s, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM `interview_questions` AS iq WHERE iq.position = %s))",
        (position, question, question_type, position),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_interview_question(id: str, position: str, question: str, question_type: str = "oral") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `interview_questions` SET position=%s, question=%s, question_type=%s WHERE id=%s",
        (position, question, question_type, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_interview_question(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `interview_questions` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Interview answers (a candidate's recorded answer to a question) ─────────

def _ensure_interview_answers_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `interview_answers` (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            application_id INT NOT NULL,
            question_id    INT NOT NULL,
            answer         TEXT,
            answered_by    VARCHAR(100) NOT NULL,
            answered_at    TIMESTAMP NULL DEFAULT NULL,
            UNIQUE KEY `uq_interview_answer` (application_id, question_id, answered_by),
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES interview_questions(id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    # Migrate tables that pre-date per-panelist answers: the unique key used to
    # be (application_id, question_id) — one shared answer per question. It now
    # needs to include answered_by so each panelist gets their own row.
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE table_schema = DATABASE() AND table_name = 'interview_answers' "
        "AND index_name = 'uq_interview_answer'"
    )
    (index_col_count,) = cursor.fetchone()
    if index_col_count not in (0, 3):
        cursor.execute("UPDATE `interview_answers` SET answered_by = '' WHERE answered_by IS NULL")
        # `uq_interview_answer` is the only index covering application_id, so MySQL
        # refuses to drop it while the application_id FK depends on it. Add a
        # throwaway supporting index first so the FK survives the swap.
        cursor.execute(
            "SELECT 1 FROM information_schema.STATISTICS "
            "WHERE table_schema = DATABASE() AND table_name = 'interview_answers' "
            "AND index_name = 'idx_interview_answers_application_id_tmp'"
        )
        if not cursor.fetchone():
            try:
                cursor.execute(
                    "ALTER TABLE `interview_answers` "
                    "ADD INDEX `idx_interview_answers_application_id_tmp` (application_id)"
                )
            except mysql.connector.Error as e:
                # 1061 = duplicate key name: another concurrent caller already
                # added it between our check and this ALTER.
                if e.errno != 1061:
                    raise
        try:
            cursor.execute("ALTER TABLE `interview_answers` DROP INDEX `uq_interview_answer`")
        except mysql.connector.Error:
            pass
        try:
            cursor.execute(
                "ALTER TABLE `interview_answers` ADD UNIQUE KEY `uq_interview_answer` "
                "(application_id, question_id, answered_by)"
            )
        except mysql.connector.Error as e:
            if e.errno != 1061:
                raise
        try:
            cursor.execute(
                "ALTER TABLE `interview_answers` DROP INDEX `idx_interview_answers_application_id_tmp`"
            )
        except mysql.connector.Error:
            pass
    cursor.execute(
        "SELECT IS_NULLABLE FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'interview_answers' AND column_name = 'answered_by'"
    )
    row = cursor.fetchone()
    if row and row[0] == "YES":
        cursor.execute("UPDATE `interview_answers` SET answered_by = '' WHERE answered_by IS NULL")
        cursor.execute("ALTER TABLE `interview_answers` MODIFY COLUMN `answered_by` VARCHAR(100) NOT NULL")


def init_interview_answers():
    """Create the interview_answers table (depends on interview_questions)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_interview_answers_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_interview_qa_for_panelist(application_id: str, position: str, panelist_username: str) -> list[dict]:
    """Every interview question configured for the candidate's position,
    left-joined with only this panelist's own answer for this application."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT q.id AS question_id, q.question, q.question_type, a.answer, a.answered_at "
        "FROM `interview_questions` q "
        "LEFT JOIN `interview_answers` a "
        "  ON a.question_id = q.id AND a.application_id = %s AND a.answered_by = %s "
        "WHERE q.position = %s ORDER BY q.sort_order, q.id",
        (application_id, panelist_username, position),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_interview_qa_aggregated(application_id: str, position: str) -> list[dict]:
    """Every interview question configured for the candidate's position, each
    with the full list of every panelist's answer for this application (for
    the admin/secretary aggregated view)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT q.id AS question_id, q.question, q.question_type, "
        "a.answered_by, a.answer, a.answered_at, "
        "u.surname, u.other_names, pa.panel_role "
        "FROM `interview_questions` q "
        "LEFT JOIN `interview_answers` a "
        "  ON a.question_id = q.id AND a.application_id = %s "
        "LEFT JOIN `users` u ON u.username = a.answered_by "
        "LEFT JOIN `panel_assignments` pa ON pa.username = a.answered_by AND pa.position = q.position "
        "WHERE q.position = %s ORDER BY q.sort_order, q.id",
        (application_id, position),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    questions: dict[int, dict] = {}
    order: list[int] = []
    for r in rows:
        qid = r["question_id"]
        if qid not in questions:
            questions[qid] = {
                "question_id": qid, "question": r["question"], "question_type": r["question_type"],
                "answers": [],
            }
            order.append(qid)
        if r["answered_by"]:
            name = f"{r.get('surname') or ''} {r.get('other_names') or ''}".strip() or r["answered_by"]
            questions[qid]["answers"].append({
                "answered_by": r["answered_by"], "panelist_name": name,
                "panel_role": r.get("panel_role") or "member",
                "answer": r["answer"], "answered_at": r["answered_at"],
            })
    return [questions[qid] for qid in order]


def upsert_interview_answer(application_id: str, question_id: str, answer: str, answered_by: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `interview_answers` (application_id, question_id, answer, answered_by, answered_at) "
        "VALUES (%s, %s, %s, %s, NOW()) "
        "ON DUPLICATE KEY UPDATE answer=VALUES(answer), answered_at=NOW()",
        (application_id, question_id, answer or None, answered_by),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Campaign locations (routes/venues plotted on the campaign map) ──────────

CAMPAIGN_LOCATION_STATUSES = ["Planned", "Active", "Completed"]
_CAMPAIGN_LOCATION_STATUS_ENUM_SQL = "ENUM({}) DEFAULT 'Planned'".format(
    ",".join(f"'{s}'" for s in CAMPAIGN_LOCATION_STATUSES)
)


def _ensure_campaign_locations_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `campaign_locations` (
            id                 INT AUTO_INCREMENT PRIMARY KEY,
            name               VARCHAR(255) NOT NULL,
            campaign           VARCHAR(255),
            description        TEXT,
            address            VARCHAR(255),
            county             VARCHAR(100),
            county_code        VARCHAR(20),
            constituency       VARCHAR(100),
            constituency_code  VARCHAR(20),
            ward               VARCHAR(100),
            ward_code          VARCHAR(20),
            ward_id            VARCHAR(4),
            latitude           DOUBLE,
            longitude          DOUBLE,
            status             {_CAMPAIGN_LOCATION_STATUS_ENUM_SQL},
            notes              TEXT,
            date_from          DATE,
            date_to            DATE,
            banner_image       VARCHAR(512),
            published          TINYINT(1) NOT NULL DEFAULT 0,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("date_from",     "DATE"),
        ("date_to",       "DATE"),
        ("banner_image",  "VARCHAR(512)"),
        ("published",     "TINYINT(1) NOT NULL DEFAULT 0"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'campaign_locations' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `campaign_locations` ADD COLUMN `{col}` {definition}")

    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'campaign_locations' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_campaign_location_ward'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `campaign_locations` ADD CONSTRAINT `fk_campaign_location_ward` "
                "FOREIGN KEY (ward_id) REFERENCES wards(ward_id) "
                "ON DELETE SET NULL ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def init_campaign_locations():
    """Create the campaign_locations table (depends on wards)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_campaign_locations_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def get_campaign_location(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `campaign_locations` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def _campaign_locations_where(search: str, published: bool | None = None) -> tuple[str, tuple]:
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append(
            "(name LIKE %s OR campaign LIKE %s OR address LIKE %s "
            "OR county LIKE %s OR constituency LIKE %s OR ward LIKE %s)"
        )
        params += [like, like, like, like, like, like]
    if published is not None:
        clauses.append("published = %s")
        params.append(1 if published else 0)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def list_campaign_locations(
    search: str = "", published: bool | None = None, limit: int | None = None, offset: int = 0,
) -> list[dict]:
    """List campaign locations, optionally filtered by a search term matched
    against name/campaign/address/county/constituency/ward and/or publish
    state, paginated."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = _campaign_locations_where(search, published)
    query = f"SELECT * FROM `campaign_locations` {where} ORDER BY created_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (*params, limit, offset)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def count_campaign_locations(search: str = "", published: bool | None = None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _campaign_locations_where(search, published)
    cursor.execute(f"SELECT COUNT(*) FROM `campaign_locations` {where}", params)
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def count_campaign_locations_by_publish_state(search: str = "") -> dict[str, int]:
    return {
        "published": count_campaign_locations(search, published=True),
        "draft":     count_campaign_locations(search, published=False),
    }


def add_campaign_location(
    *, name: str, campaign: str = "", description: str = "", address: str = "",
    county: str = "", county_code: str = "", constituency: str = "", constituency_code: str = "",
    ward: str = "", ward_code: str = "", ward_id: str | None = None,
    latitude: float | None = None, longitude: float | None = None,
    status: str = "Planned", notes: str = "",
    date_from: date | None = None, date_to: date | None = None,
) -> int:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `campaign_locations` "
        "(name, campaign, description, address, county, county_code, constituency, constituency_code, "
        " ward, ward_code, ward_id, latitude, longitude, status, notes, date_from, date_to) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (name, campaign or None, description or None, address or None,
         county or None, county_code or None, constituency or None, constituency_code or None,
         ward or None, ward_code or None, ward_id, latitude, longitude, status, notes or None,
         date_from, date_to),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_campaign_location(
    id: str, *, name: str, campaign: str = "", description: str = "", address: str = "",
    county: str = "", county_code: str = "", constituency: str = "", constituency_code: str = "",
    ward: str = "", ward_code: str = "", ward_id: str | None = None,
    latitude: float | None = None, longitude: float | None = None,
    status: str = "Planned", notes: str = "",
    date_from: date | None = None, date_to: date | None = None,
) -> None:
    ward_id = _pad_ward_id(ward_id) if ward_id else None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `campaign_locations` SET "
        "name=%s, campaign=%s, description=%s, address=%s, "
        "county=%s, county_code=%s, constituency=%s, constituency_code=%s, "
        "ward=%s, ward_code=%s, ward_id=%s, latitude=%s, longitude=%s, status=%s, notes=%s, "
        "date_from=%s, date_to=%s "
        "WHERE id=%s",
        (name, campaign or None, description or None, address or None,
         county or None, county_code or None, constituency or None, constituency_code or None,
         ward or None, ward_code or None, ward_id, latitude, longitude, status, notes or None,
         date_from, date_to, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def set_campaign_location_published(id: str, published: bool) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `campaign_locations` SET published=%s WHERE id=%s",
        (1 if published else 0, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def set_campaign_location_status(id: str, status: str) -> None:
    """Set only the status column (e.g. the one-click 'Mark Complete' action),
    without touching any other field."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE `campaign_locations` SET status=%s WHERE id=%s", (status, id))
    conn.commit()
    cursor.close()
    conn.close()


def delete_campaign_location(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT banner_image FROM `campaign_locations` WHERE id = %s", (id,))
    row = cursor.fetchone()
    banner = row["banner_image"] if row else None
    cursor.execute("SELECT filename FROM `campaign_location_media` WHERE location_id = %s", (id,))
    media_files = [r["filename"] for r in cursor.fetchall()]

    if banner:
        if cloudinary_storage.is_remote_ref(banner):
            cloudinary_storage.destroy(banner)
        else:
            (CAMPAIGN_BANNERS_DIR / str(id) / banner).unlink(missing_ok=True)
    for fname in media_files:
        if cloudinary_storage.is_remote_ref(fname):
            cloudinary_storage.destroy(fname)
        else:
            (CAMPAIGN_MEDIA_DIR / str(id) / fname).unlink(missing_ok=True)

    # `campaign_location_media` rows are removed automatically via ON DELETE CASCADE.
    cursor.execute("DELETE FROM `campaign_locations` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    for d in (CAMPAIGN_BANNERS_DIR / str(id), CAMPAIGN_MEDIA_DIR / str(id)):
        try:
            d.rmdir()
        except OSError:
            pass


# ── Campaign location banner (single photo, shown on the public site) ───────

def set_campaign_location_banner(location_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured, otherwise write the new banner
    under CAMPAIGN_BANNERS_DIR/<location_id>/. Points
    campaign_locations.banner_image at it, and deletes the previous banner
    (from Cloudinary or disk, whichever it was on). Returns the new stored
    value (a Cloudinary URL or a local filename)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    loc_dir = CAMPAIGN_BANNERS_DIR / str(location_id)
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/campaign_banners/{location_id}", public_id=stored_name)
    if remote_url:
        stored_value = remote_url
    else:
        loc_dir.mkdir(parents=True, exist_ok=True)
        (loc_dir / stored_name).write_bytes(file_bytes)
        stored_value = stored_name

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT banner_image FROM `campaign_locations` WHERE id = %s", (location_id,))
    row = cursor.fetchone()
    old_banner = row["banner_image"] if row else None
    cursor.execute(
        "UPDATE `campaign_locations` SET banner_image=%s WHERE id=%s", (stored_value, location_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    if old_banner and old_banner != stored_value:
        if cloudinary_storage.is_remote_ref(old_banner):
            cloudinary_storage.destroy(old_banner)
        else:
            (loc_dir / old_banner).unlink(missing_ok=True)
    return stored_value


def remove_campaign_location_banner(location_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT banner_image FROM `campaign_locations` WHERE id = %s", (location_id,))
    row = cursor.fetchone()
    old_banner = row["banner_image"] if row else None
    cursor.execute("UPDATE `campaign_locations` SET banner_image=NULL WHERE id=%s", (location_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if old_banner:
        if cloudinary_storage.is_remote_ref(old_banner):
            cloudinary_storage.destroy(old_banner)
        else:
            (CAMPAIGN_BANNERS_DIR / str(location_id) / old_banner).unlink(missing_ok=True)


def get_campaign_location_banner_bytes(location_id) -> tuple[bytes, str] | None:
    """Return (file_bytes, stored_filename) for the location's banner, or
    None if there's no banner set or the file is missing."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT banner_image FROM `campaign_locations` WHERE id = %s", (location_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row or not row["banner_image"]:
        return None
    if cloudinary_storage.is_remote_ref(row["banner_image"]):
        data = cloudinary_storage.fetch_bytes(row["banner_image"])
        return (data, row["banner_image"]) if data is not None else None
    path = CAMPAIGN_BANNERS_DIR / str(location_id) / row["banner_image"]
    if not path.exists():
        return None
    return path.read_bytes(), row["banner_image"]


# ── Campaign location media gallery (photos of completed rallies) ───────────

def _ensure_campaign_location_media_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `campaign_location_media` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            location_id       INT NOT NULL,
            filename          VARCHAR(512) NOT NULL,
            original_filename VARCHAR(255),
            uploaded_by       VARCHAR(100),
            uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (location_id),
            FOREIGN KEY (location_id) REFERENCES campaign_locations(id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def init_campaign_location_media():
    """Create the campaign_location_media table (depends on campaign_locations)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_campaign_location_media_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def save_campaign_media_file(location_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured; otherwise write uploaded bytes
    under CAMPAIGN_MEDIA_DIR/<location_id>/. Returns either the Cloudinary
    URL or the unique stored filename (safe for the filesystem, collision-free)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/campaign_media/{location_id}", public_id=stored_name)
    if remote_url:
        return remote_url
    loc_dir = CAMPAIGN_MEDIA_DIR / str(location_id)
    loc_dir.mkdir(parents=True, exist_ok=True)
    (loc_dir / stored_name).write_bytes(file_bytes)
    return stored_name


def add_campaign_location_media(location_id, filename: str, original_filename: str, uploaded_by: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `campaign_location_media` (location_id, filename, original_filename, uploaded_by) "
        "VALUES (%s, %s, %s, %s)",
        (location_id, filename, original_filename, uploaded_by),
    )
    conn.commit()
    media_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return media_id


def list_campaign_location_media(location_id) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `campaign_location_media` WHERE location_id = %s ORDER BY uploaded_at DESC",
        (location_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_campaign_location_media(media_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `campaign_location_media` WHERE id = %s", (media_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_campaign_location_media_bytes(media_id: int) -> tuple[bytes, str] | None:
    """Return (file_bytes, display_filename) for download, or None if missing."""
    media = get_campaign_location_media(media_id)
    if not media:
        return None
    display_name = media["original_filename"] or media["filename"]
    if cloudinary_storage.is_remote_ref(media["filename"]):
        data = cloudinary_storage.fetch_bytes(media["filename"])
        return (data, display_name) if data is not None else None
    path = CAMPAIGN_MEDIA_DIR / str(media["location_id"]) / media["filename"]
    if not path.exists():
        return None
    return path.read_bytes(), display_name


def delete_campaign_location_media(media_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT location_id, filename FROM `campaign_location_media` WHERE id = %s", (media_id,),
    )
    row = cursor.fetchone()
    cursor.execute("DELETE FROM `campaign_location_media` WHERE id = %s", (media_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if row:
        if cloudinary_storage.is_remote_ref(row["filename"]):
            cloudinary_storage.destroy(row["filename"])
        else:
            (CAMPAIGN_MEDIA_DIR / str(row["location_id"]) / row["filename"]).unlink(missing_ok=True)


# ── Campaign location team members ───────────────────────────────────────────

def _ensure_location_team_members_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `location_team_members` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            location_id INT NOT NULL,
            username    VARCHAR(100) NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_location_member` (location_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_location_member_location",
         "ALTER TABLE `location_team_members` ADD CONSTRAINT `fk_location_member_location` "
         "FOREIGN KEY (location_id) REFERENCES campaign_locations(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_location_member_user",
         "ALTER TABLE `location_team_members` ADD CONSTRAINT `fk_location_member_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'location_team_members' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_location_team():
    """Create the location_team_members table (depends on campaign_locations + users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_location_team_members_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_location_team_members(location_id) -> list[dict]:
    """Team members assigned to a location, with enough profile info for display."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ltm.id, u.username, u.surname, u.other_names, u.email "
        "FROM `location_team_members` ltm "
        "JOIN `users` u ON u.username = ltm.username "
        "WHERE ltm.location_id = %s ORDER BY u.surname, u.other_names",
        (location_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def add_location_team_member(location_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT IGNORE INTO `location_team_members` (location_id, username) VALUES (%s, %s)",
        (location_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_location_team_member(location_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM `location_team_members` WHERE location_id = %s AND username = %s",
        (location_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Campaign teams (named sub-groups within the campaign roster, e.g. "Team
# Swat") — distinct from the campaign/election TEAM_TYPE split above. ───────

def _ensure_campaign_teams_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `campaign_teams` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(200) UNIQUE NOT NULL,
            description TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def _ensure_campaign_team_members_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `campaign_team_members` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            team_id    INT NOT NULL,
            username   VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_campaign_team_member` (team_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_campaign_team_member_team",
         "ALTER TABLE `campaign_team_members` ADD CONSTRAINT `fk_campaign_team_member_team` "
         "FOREIGN KEY (team_id) REFERENCES campaign_teams(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_campaign_team_member_user",
         "ALTER TABLE `campaign_team_members` ADD CONSTRAINT `fk_campaign_team_member_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'campaign_team_members' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_campaign_teams():
    """Create the campaign_teams and campaign_team_members tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_campaign_teams_table(cursor)
    _ensure_campaign_team_members_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_campaign_teams(search: str = "") -> list[dict]:
    """Named campaign teams with a member_count, optionally filtered by name/description."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = "WHERE ct.name LIKE %s OR ct.description LIKE %s"
        params = (like, like)
    cursor.execute(
        "SELECT ct.*, "
        "(SELECT COUNT(*) FROM campaign_team_members m WHERE m.team_id = ct.id) AS member_count "
        f"FROM `campaign_teams` ct {where} ORDER BY ct.name",
        params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_campaign_team(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `campaign_teams` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_campaign_team(name: str, description: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `campaign_teams` (name, description) VALUES (%s, %s)",
        (name, description or None),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_campaign_team(id: str, name: str, description: str = "") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `campaign_teams` SET name=%s, description=%s WHERE id=%s",
        (name, description or None, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_campaign_team(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `campaign_teams` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def list_campaign_team_members(team_id) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ctm.id, u.username, u.surname, u.other_names, u.email "
        "FROM `campaign_team_members` ctm "
        "JOIN `users` u ON u.username = ctm.username "
        "WHERE ctm.team_id = %s ORDER BY u.surname, u.other_names",
        (team_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def add_campaign_team_member(team_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT IGNORE INTO `campaign_team_members` (team_id, username) VALUES (%s, %s)",
        (team_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_campaign_team_member(team_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM `campaign_team_members` WHERE team_id = %s AND username = %s",
        (team_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Shared materials inventory (used by both campaign and election teams) ──

def _ensure_materials_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `materials` (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            name          VARCHAR(255) NOT NULL,
            unit          VARCHAR(50),
            quantity      INT DEFAULT 0,
            description   TEXT,
            material_type ENUM('campaign', 'election', 'both') NOT NULL DEFAULT 'both',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def _migrate_legacy_materials_table(cursor, legacy_table: str, material_type: str,
                                     assignments_table: str, fk_name: str):
    """One-off upgrade path: earlier versions kept a separate materials table
    per team type (e.g. `campaign_materials`). Copy any such rows into the
    shared `materials` table (remapping ids, since the two legacy tables
    auto-incremented independently and could collide), repoint the
    assignments table's FK at `materials`, then drop the legacy table."""
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (legacy_table,),
    )
    if not cursor.fetchone():
        return

    cursor.execute(
        f"SELECT id, name, unit, quantity, description, created_at, updated_at FROM `{legacy_table}`"
    )
    legacy_rows = cursor.fetchall()

    id_map = {}
    for old_id, name, unit, quantity, description, created_at, updated_at in legacy_rows:
        cursor.execute(
            "INSERT INTO `materials` (name, unit, quantity, description, material_type, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (name, unit, quantity, description, material_type, created_at, updated_at),
        )
        id_map[old_id] = cursor.lastrowid

    cursor.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (assignments_table,),
    )
    if cursor.fetchone():
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = %s "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (assignments_table, fk_name),
        )
        if cursor.fetchone():
            cursor.execute(f"ALTER TABLE `{assignments_table}` DROP FOREIGN KEY `{fk_name}`")
        for old_id, new_id in id_map.items():
            cursor.execute(
                f"UPDATE `{assignments_table}` SET material_id = %s WHERE material_id = %s",
                (new_id, old_id),
            )

    cursor.execute(f"DROP TABLE `{legacy_table}`")


def init_materials():
    """Create the shared materials table (used by both campaign and election
    team material assignments)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_materials_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_materials(search: str = "", material_type: str | None = None) -> list[dict]:
    """`material_type`, if given, includes materials of that type plus 'both'."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    clauses, params = [], []
    if search:
        like = f"%{search}%"
        clauses.append("(name LIKE %s OR description LIKE %s)")
        params += [like, like]
    if material_type:
        clauses.append("(material_type = %s OR material_type = 'both')")
        params.append(material_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor.execute(f"SELECT * FROM `materials` {where} ORDER BY name", params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_material(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `materials` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_material(name: str, unit: str = "", quantity: int = 0, description: str = "",
                  material_type: str = "both") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `materials` (name, unit, quantity, description, material_type) "
        "VALUES (%s, %s, %s, %s, %s)",
        (name, unit or None, quantity, description or None, material_type),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_material(id: str, name: str, unit: str = "", quantity: int = 0, description: str = "",
                     material_type: str = "both") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `materials` SET name=%s, unit=%s, quantity=%s, description=%s, material_type=%s WHERE id=%s",
        (name, unit or None, quantity, description or None, material_type, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_material(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `materials` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def assigned_material_quantity(material_id) -> int:
    """Total quantity assigned to teams, across both campaign and election assignments."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM `campaign_material_assignments` WHERE material_id = %s",
        (material_id,),
    )
    campaign_total = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM `election_material_assignments` WHERE material_id = %s",
        (material_id,),
    )
    election_total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return int(campaign_total) + int(election_total)


# ── Campaign material assignments (materials <-> named campaign teams) ─────

def _ensure_campaign_material_assignments_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `campaign_material_assignments` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            material_id INT NOT NULL,
            team_id     INT NOT NULL,
            quantity    INT NOT NULL DEFAULT 0,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_material_team` (material_id, team_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_material_assignment_material",
         "ALTER TABLE `campaign_material_assignments` ADD CONSTRAINT `fk_material_assignment_material` "
         "FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_material_assignment_team",
         "ALTER TABLE `campaign_material_assignments` ADD CONSTRAINT `fk_material_assignment_team` "
         "FOREIGN KEY (team_id) REFERENCES campaign_teams(id) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'campaign_material_assignments' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_campaign_materials():
    """Create the campaign_material_assignments table (depends on the shared
    materials table and campaign_teams); migrates any pre-existing
    campaign_materials rows into the shared table first."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _migrate_legacy_materials_table(
        cursor, legacy_table="campaign_materials", material_type="campaign",
        assignments_table="campaign_material_assignments", fk_name="fk_material_assignment_material",
    )
    _ensure_campaign_material_assignments_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_material_assignments(material_id) -> list[dict]:
    """Teams a material is assigned to, with the assigned quantity."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT cma.id, cma.team_id, cma.quantity, ct.name AS team_name "
        "FROM `campaign_material_assignments` cma "
        "JOIN `campaign_teams` ct ON ct.id = cma.team_id "
        "WHERE cma.material_id = %s ORDER BY ct.name",
        (material_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_team_material_assignments(team_id) -> list[dict]:
    """Materials assigned to a team, with the assigned quantity."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT cma.id, cma.material_id, cma.quantity, m.name AS material_name, m.unit "
        "FROM `campaign_material_assignments` cma "
        "JOIN `materials` m ON m.id = cma.material_id "
        "WHERE cma.team_id = %s ORDER BY m.name",
        (team_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def assign_material_to_team(material_id, team_id, quantity: int) -> None:
    """Set the quantity of a material assigned to a team (upsert)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `campaign_material_assignments` (material_id, team_id, quantity) "
        "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE quantity = VALUES(quantity)",
        (material_id, team_id, quantity),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_material_assignment(material_id, team_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM `campaign_material_assignments` WHERE material_id = %s AND team_id = %s",
        (material_id, team_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Election teams (named sub-groups of the election roster) ────────────────

def _ensure_election_teams_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `election_teams` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def _ensure_election_team_members_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `election_team_members` (
            id       INT AUTO_INCREMENT PRIMARY KEY,
            team_id  INT NOT NULL,
            username VARCHAR(150) NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_election_team_member` (team_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_election_team_member_team",
         "ALTER TABLE `election_team_members` ADD CONSTRAINT `fk_election_team_member_team` "
         "FOREIGN KEY (team_id) REFERENCES election_teams(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_election_team_member_user",
         "ALTER TABLE `election_team_members` ADD CONSTRAINT `fk_election_team_member_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'election_team_members' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_election_teams():
    """Create the election_teams and election_team_members tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_election_teams_table(cursor)
    _ensure_election_team_members_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_election_teams(search: str = "") -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    where, params = "", ()
    if search:
        like = f"%{search}%"
        where = "WHERE et.name LIKE %s OR et.description LIKE %s"
        params = (like, like)
    cursor.execute(
        "SELECT et.*, "
        "(SELECT COUNT(*) FROM election_team_members m WHERE m.team_id = et.id) AS member_count "
        f"FROM `election_teams` et {where} ORDER BY et.name",
        params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_election_team(id: str) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `election_teams` WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def add_election_team(name: str, description: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `election_teams` (name, description) VALUES (%s, %s)",
        (name, description or None),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_election_team(id: str, name: str, description: str = "") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `election_teams` SET name=%s, description=%s WHERE id=%s",
        (name, description or None, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_election_team(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `election_teams` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()


def list_election_team_members(team_id) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT etm.id, u.username, u.surname, u.other_names, u.email "
        "FROM `election_team_members` etm "
        "JOIN `users` u ON u.username = etm.username "
        "WHERE etm.team_id = %s ORDER BY u.surname, u.other_names",
        (team_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def add_election_team_member(team_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT IGNORE INTO `election_team_members` (team_id, username) VALUES (%s, %s)",
        (team_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_election_team_member(team_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM `election_team_members` WHERE team_id = %s AND username = %s",
        (team_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Election material assignments (materials <-> named election teams) ─────

def _ensure_election_material_assignments_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `election_material_assignments` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            material_id INT NOT NULL,
            team_id     INT NOT NULL,
            quantity    INT NOT NULL DEFAULT 0,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_election_material_team` (material_id, team_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_election_material_assignment_material",
         "ALTER TABLE `election_material_assignments` ADD CONSTRAINT `fk_election_material_assignment_material` "
         "FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_election_material_assignment_team",
         "ALTER TABLE `election_material_assignments` ADD CONSTRAINT `fk_election_material_assignment_team` "
         "FOREIGN KEY (team_id) REFERENCES election_teams(id) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'election_material_assignments' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_election_materials():
    """Create the election_material_assignments table (depends on the shared
    materials table and election_teams); migrates any pre-existing
    election_materials rows into the shared table first."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _migrate_legacy_materials_table(
        cursor, legacy_table="election_materials", material_type="election",
        assignments_table="election_material_assignments", fk_name="fk_election_material_assignment_material",
    )
    _ensure_election_material_assignments_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def list_election_material_assignments(material_id) -> list[dict]:
    """Teams a material is assigned to, with the assigned quantity."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ema.id, ema.team_id, ema.quantity, et.name AS team_name "
        "FROM `election_material_assignments` ema "
        "JOIN `election_teams` et ON et.id = ema.team_id "
        "WHERE ema.material_id = %s ORDER BY et.name",
        (material_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_election_team_material_assignments(team_id) -> list[dict]:
    """Materials assigned to a team, with the assigned quantity."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT ema.id, ema.material_id, ema.quantity, m.name AS material_name, m.unit "
        "FROM `election_material_assignments` ema "
        "JOIN `materials` m ON m.id = ema.material_id "
        "WHERE ema.team_id = %s ORDER BY m.name",
        (team_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def assign_election_material_to_team(material_id, team_id, quantity: int) -> None:
    """Set the quantity of a material assigned to a team (upsert)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `election_material_assignments` (material_id, team_id, quantity) "
        "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE quantity = VALUES(quantity)",
        (material_id, team_id, quantity),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_election_material_assignment(material_id, team_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM `election_material_assignments` WHERE material_id = %s AND team_id = %s",
        (material_id, team_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ── Calls (WebRTC audio call signaling between two users) ──────────────────
# Signaling (offer/answer SDP + ICE candidates) is exchanged entirely through
# these tables and picked up by polling, matching the chat_messages pattern
# elsewhere in this file (no separate websocket/signaling server involved).

CALL_STATUSES = ["ringing", "accepted", "declined", "ended", "missed"]
_CALL_STATUS_ENUM_SQL = "ENUM({}) DEFAULT 'ringing'".format(
    ",".join(f"'{s}'" for s in CALL_STATUSES)
)


def _ensure_calls_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `calls` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            caller_username   VARCHAR(100) NOT NULL,
            callee_username   VARCHAR(100) NOT NULL,
            status            {_CALL_STATUS_ENUM_SQL},
            offer_sdp         MEDIUMTEXT,
            answer_sdp        MEDIUMTEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            ended_at          TIMESTAMP NULL DEFAULT NULL,
            INDEX (caller_username, status),
            INDEX (callee_username, status)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_call_caller",
         "ALTER TABLE `calls` ADD CONSTRAINT `fk_call_caller` "
         "FOREIGN KEY (caller_username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_call_callee",
         "ALTER TABLE `calls` ADD CONSTRAINT `fk_call_callee` "
         "FOREIGN KEY (callee_username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'calls' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def _ensure_call_ice_candidates_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `call_ice_candidates` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            call_id    INT NOT NULL,
            username   VARCHAR(100) NOT NULL,
            candidate  TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (call_id, id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_call_ice_candidate_call",
         "ALTER TABLE `call_ice_candidates` ADD CONSTRAINT `fk_call_ice_candidate_call` "
         "FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("fk_call_ice_candidate_user",
         "ALTER TABLE `call_ice_candidates` ADD CONSTRAINT `fk_call_ice_candidate_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'call_ice_candidates' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_calls():
    """Create the calls and call_ice_candidates tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_calls_table(cursor)
    _ensure_call_ice_candidates_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def create_call(caller_username: str, callee_username: str, offer_sdp: str) -> int:
    """Start a new call: caller has already generated a WebRTC offer. Any of
    the caller's or callee's older ringing/accepted calls are marked ended
    first, so a user can only be in one active call signaling row at a time."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `calls` SET status='ended', ended_at=NOW() "
        "WHERE status IN ('ringing','accepted') "
        "AND (caller_username IN (%s, %s) OR callee_username IN (%s, %s))",
        (caller_username, callee_username, caller_username, callee_username),
    )
    cursor.execute(
        "INSERT INTO `calls` (caller_username, callee_username, status, offer_sdp) "
        "VALUES (%s, %s, 'ringing', %s)",
        (caller_username, callee_username, offer_sdp),
    )
    conn.commit()
    call_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return call_id


def get_call(call_id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `calls` WHERE id = %s", (call_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_incoming_call(username: str) -> dict | None:
    """The most recent call still ringing for this user as callee, if any."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `calls` WHERE callee_username = %s AND status = 'ringing' "
        "ORDER BY created_at DESC LIMIT 1",
        (username,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_active_call_for_user(username: str) -> dict | None:
    """The most recent call (as caller or callee) that's still ringing or
    accepted — lets each side's UI figure out its current call state by polling."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `calls` WHERE (caller_username = %s OR callee_username = %s) "
        "AND status IN ('ringing','accepted') "
        "ORDER BY created_at DESC LIMIT 1",
        (username, username),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def accept_call(call_id, answer_sdp: str) -> None:
    """Callee accepted: record their SDP answer and flip the call to accepted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `calls` SET status='accepted', answer_sdp=%s WHERE id=%s AND status='ringing'",
        (answer_sdp, call_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def decline_call(call_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `calls` SET status='declined', ended_at=NOW() WHERE id=%s AND status='ringing'",
        (call_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()


def end_call(call_id) -> None:
    """Hang up: either party can call this once, from either 'ringing' or
    'accepted' — a no-op if the call was already ended/declined."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `calls` SET status='ended', ended_at=NOW() "
        "WHERE id=%s AND status IN ('ringing','accepted')",
        (call_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()


def mark_call_missed(call_id) -> None:
    """Caller gave up waiting for an answer (e.g. UI-side ring timeout)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `calls` SET status='missed', ended_at=NOW() WHERE id=%s AND status='ringing'",
        (call_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()


def add_ice_candidate(call_id, username: str, candidate_json: str) -> int:
    """`candidate_json` is the JSON.stringify'd RTCIceCandidate from the browser."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `call_ice_candidates` (call_id, username, candidate) VALUES (%s, %s, %s)",
        (call_id, username, candidate_json),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def list_ice_candidates(call_id, exclude_username: str, since_id: int = 0) -> list[dict]:
    """The other party's ICE candidates for this call, newer than `since_id`
    — callers poll this with the highest id they've already consumed so they
    only ever apply each candidate once."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `call_ice_candidates` "
        "WHERE call_id = %s AND username != %s AND id > %s ORDER BY id",
        (call_id, exclude_username, since_id),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── Events (calendar: personal / group / general) ───────────────────────────
# General events are visible to everyone. Personal/group events are only
# visible to their creator and whoever is listed in `event_members` — the
# creator is always added to that list so a single visibility rule covers
# both "just me" and "me + some teammates" cases.
#
# Recurring events store only a recurrence *rule* on the master row (freq,
# interval, unit, days-of-week, until) — occurrences are never materialized
# as rows. `list_events_for_user` expands the rule into concrete (start, end)
# dates on the fly, scoped to whatever month is being viewed, so a rule with
# no end date still costs O(days in that month) rather than growing forever.

EVENT_TYPES = ["personal", "group", "general"]
RECURRENCE_FREQUENCIES = ["none", "daily", "weekly", "monthly", "custom"]
RECURRENCE_UNITS = ["day", "week", "month"]


def _ensure_events_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `events` (
            id                       INT AUTO_INCREMENT PRIMARY KEY,
            event_type               ENUM('personal','group','general') NOT NULL DEFAULT 'general',
            title                    VARCHAR(255) NOT NULL DEFAULT '',
            description              TEXT NOT NULL,
            start_date               DATE NOT NULL,
            end_date                 DATE NOT NULL,
            start_time               TIME NULL,
            end_time                 TIME NULL,
            whole_day                TINYINT(1) NOT NULL DEFAULT 0,
            recurrence_freq          ENUM('none','daily','weekly','monthly','custom') NOT NULL DEFAULT 'none',
            recurrence_interval      INT NOT NULL DEFAULT 1,
            recurrence_unit          ENUM('day','week','month') NULL,
            recurrence_days_of_week  VARCHAR(20) NULL,
            recurrence_until         DATE NULL,
            created_by               VARCHAR(100) NOT NULL,
            created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX (start_date, end_date)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    # Add new columns to existing tables that pre-date this schema
    for col, definition in [
        ("title",                   "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("start_time",              "TIME NULL"),
        ("end_time",                "TIME NULL"),
        ("whole_day",               "TINYINT(1) NOT NULL DEFAULT 0"),
        ("recurrence_freq",         "ENUM('none','daily','weekly','monthly','custom') NOT NULL DEFAULT 'none'"),
        ("recurrence_interval",     "INT NOT NULL DEFAULT 1"),
        ("recurrence_unit",         "ENUM('day','week','month') NULL"),
        ("recurrence_days_of_week", "VARCHAR(20) NULL"),
        ("recurrence_until",        "DATE NULL"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'events' AND column_name = %s",
            (col,),
        )
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE `events` ADD COLUMN `{col}` {definition}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `event_members` (
            event_id  INT NOT NULL,
            username  VARCHAR(100) NOT NULL,
            PRIMARY KEY (event_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for table, fk_name, ddl in [
        ("events", "fk_event_creator",
         "ALTER TABLE `events` ADD CONSTRAINT `fk_event_creator` "
         "FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("event_members", "fk_event_member_event",
         "ALTER TABLE `event_members` ADD CONSTRAINT `fk_event_member_event` "
         "FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE"),
        ("event_members", "fk_event_member_user",
         "ALTER TABLE `event_members` ADD CONSTRAINT `fk_event_member_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = %s "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (table, fk_name),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                # 1826 = duplicate FK constraint name: another concurrent caller
                # already added it between our check and this ALTER.
                if e.errno != 1826:
                    raise


def init_events():
    """Create the events + event_members tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_events_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def _set_event_members(cursor, event_id, event_type: str, created_by: str, member_usernames):
    cursor.execute("DELETE FROM `event_members` WHERE event_id = %s", (event_id,))
    if event_type != "general":
        members = {created_by, *(member_usernames or [])}
        cursor.executemany(
            "INSERT IGNORE INTO `event_members` (event_id, username) VALUES (%s, %s)",
            [(event_id, u) for u in members],
        )


def _time_from_db(value):
    """mysql-connector returns TIME columns as timedelta, not time — normalize."""
    if isinstance(value, timedelta):
        total_minutes, seconds = divmod(int(value.total_seconds()), 60)
        hours, minutes = divmod(total_minutes, 60)
        return dt_time(hours % 24, minutes, seconds)
    return value


def _normalize_event_row(row: dict) -> dict:
    row["start_time"] = _time_from_db(row.get("start_time"))
    row["end_time"] = _time_from_db(row.get("end_time"))
    return row


def create_event(
    event_type: str, title: str, description: str, start_date, end_date,
    created_by: str, member_usernames: list[str] | None = None,
    start_time=None, end_time=None, whole_day: bool = False,
    recurrence_freq: str = "none", recurrence_interval: int = 1,
    recurrence_unit: str | None = None, recurrence_days_of_week: str | None = None,
    recurrence_until=None,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `events` "
        "(event_type, title, description, start_date, end_date, start_time, end_time, whole_day, "
        " recurrence_freq, recurrence_interval, recurrence_unit, recurrence_days_of_week, "
        " recurrence_until, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (event_type, title, description, start_date, end_date, start_time, end_time, whole_day,
         recurrence_freq, recurrence_interval, recurrence_unit, recurrence_days_of_week,
         recurrence_until, created_by),
    )
    event_id = cursor.lastrowid
    _set_event_members(cursor, event_id, event_type, created_by, member_usernames)
    conn.commit()
    cursor.close()
    conn.close()
    return event_id


def get_event(event_id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `events` WHERE id = %s", (event_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return _normalize_event_row(row) if row else None


def list_event_members(event_id) -> list[dict]:
    """Members of an event, with display-name fields, alphabetical."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT u.username, u.other_names, u.surname, u.position, u.role "
        "FROM `event_members` m JOIN `users` u ON u.username = m.username "
        "WHERE m.event_id = %s ORDER BY u.other_names, u.surname",
        (event_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def add_event_member(event_id, username: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT IGNORE INTO `event_members` (event_id, username) VALUES (%s, %s)",
        (event_id, username),
    )
    conn.commit()
    cursor.close()
    conn.close()


def remove_event_member(event_id, username: str) -> None:
    """No-op if `username` is the event's creator — the creator always stays
    a member so the visibility rule in `list_events_for_user` keeps holding."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_by FROM `events` WHERE id = %s", (event_id,))
    row = cursor.fetchone()
    if row and row[0] != username:
        cursor.execute(
            "DELETE FROM `event_members` WHERE event_id = %s AND username = %s",
            (event_id, username),
        )
        conn.commit()
    cursor.close()
    conn.close()


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, _calendar.monthrange(year, month)[1])
    return date(year, month, day)


_MAX_OCCURRENCE_STEPS = 3660  # generous safety cap (~10 years of daily steps)


def _expand_event_occurrences(ev: dict, range_start: date, range_end_exclusive: date) -> list[tuple[date, date]]:
    """(occ_start, occ_end) pairs for this event's occurrences that overlap
    [range_start, range_end_exclusive). Each occurrence keeps the master
    event's original span length (end_date - start_date)."""
    start, end = ev["start_date"], ev["end_date"]
    duration = (end - start).days
    freq = ev.get("recurrence_freq") or "none"

    if freq == "none":
        return [(start, end)] if start < range_end_exclusive and end >= range_start else []

    until = ev.get("recurrence_until")
    last_allowed = min(until, range_end_exclusive - timedelta(days=1)) if until else range_end_exclusive - timedelta(days=1)
    if last_allowed < start:
        return []

    occurrences: list[tuple[date, date]] = []
    unit = ev.get("recurrence_unit")

    if freq in ("daily", "weekly") or (freq == "custom" and (unit or "week") == "day"):
        step_days = 1 if freq == "daily" else (7 if freq == "weekly" else max(1, ev.get("recurrence_interval") or 1))
        cur = start
        for _ in range(_MAX_OCCURRENCE_STEPS):
            if cur > last_allowed:
                break
            occ_end = cur + timedelta(days=duration)
            if occ_end >= range_start:
                occurrences.append((cur, occ_end))
            cur += timedelta(days=step_days)

    elif freq == "monthly" or (freq == "custom" and unit == "month"):
        interval = 1 if freq == "monthly" else max(1, ev.get("recurrence_interval") or 1)
        for k in range(_MAX_OCCURRENCE_STEPS):
            cur = _add_months(start, interval * k)
            if cur > last_allowed:
                break
            occ_end = cur + timedelta(days=duration)
            if occ_end >= range_start:
                occurrences.append((cur, occ_end))

    elif freq == "custom":  # unit == "week" (or unset, defaulting to week)
        interval = max(1, ev.get("recurrence_interval") or 1)
        days_raw = ev.get("recurrence_days_of_week") or ""
        dows = {int(x) for x in days_raw.split(",") if x != ""} or {start.weekday()}
        week_start = start - timedelta(days=start.weekday())  # Monday on/before the anchor
        for k in range(_MAX_OCCURRENCE_STEPS):
            block_start = week_start + timedelta(weeks=interval * k)
            if block_start > last_allowed:
                break
            for dow in sorted(dows):
                occ_start = block_start + timedelta(days=dow)
                if occ_start < start or occ_start > last_allowed:
                    continue
                occ_end = occ_start + timedelta(days=duration)
                if occ_end >= range_start:
                    occurrences.append((occ_start, occ_end))

    return occurrences


def list_events_for_user(username: str, year: int, month: int) -> list[dict]:
    """Occurrences visible to this user (general, or personal/group events
    they created or were added to) that fall within the given month, each
    annotated with its member usernames, ordered by start date. Recurring
    events are expanded into one entry per occurrence in that month; all
    occurrences of the same event share its `id`."""
    month_start = date(year, month, 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    month_end = date(next_year, next_month, 1)  # exclusive

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT DISTINCT e.* FROM `events` e "
        "LEFT JOIN `event_members` m ON m.event_id = e.id "
        "WHERE e.start_date < %s "
        "AND ((e.recurrence_freq = 'none' AND e.end_date >= %s) "
        "     OR (e.recurrence_freq != 'none' AND (e.recurrence_until IS NULL OR e.recurrence_until >= %s))) "
        "AND (e.event_type = 'general' OR e.created_by = %s OR m.username = %s) "
        "ORDER BY e.start_date",
        (month_end, month_start, month_start, username, username),
    )
    rows = [_normalize_event_row(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    if rows:
        event_ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(event_ids))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT event_id, username FROM `event_members` WHERE event_id IN ({placeholders})",
            event_ids,
        )
        members_by_event: dict[int, list[str]] = {}
        for r in cursor.fetchall():
            members_by_event.setdefault(r["event_id"], []).append(r["username"])
        cursor.close()
        conn.close()
        for r in rows:
            r["members"] = members_by_event.get(r["id"], [])

    occurrences: list[dict] = []
    for r in rows:
        for occ_start, occ_end in _expand_event_occurrences(r, month_start, month_end):
            occ = dict(r)
            occ["start_date"] = occ_start
            occ["end_date"] = occ_end
            occurrences.append(occ)
    occurrences.sort(key=lambda o: o["start_date"])
    return occurrences


def update_event(
    event_id, event_type: str, title: str, description: str, start_date, end_date,
    member_usernames: list[str] | None = None,
    start_time=None, end_time=None, whole_day: bool = False,
    recurrence_freq: str = "none", recurrence_interval: int = 1,
    recurrence_unit: str | None = None, recurrence_days_of_week: str | None = None,
    recurrence_until=None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `events` SET event_type=%s, title=%s, description=%s, start_date=%s, end_date=%s, "
        "start_time=%s, end_time=%s, whole_day=%s, recurrence_freq=%s, recurrence_interval=%s, "
        "recurrence_unit=%s, recurrence_days_of_week=%s, recurrence_until=%s WHERE id=%s",
        (event_type, title, description, start_date, end_date, start_time, end_time, whole_day,
         recurrence_freq, recurrence_interval, recurrence_unit, recurrence_days_of_week,
         recurrence_until, event_id),
    )
    cursor.execute("SELECT created_by FROM `events` WHERE id = %s", (event_id,))
    row = cursor.fetchone()
    if row:
        _set_event_members(cursor, event_id, event_type, row[0], member_usernames)
    conn.commit()
    cursor.close()
    conn.close()


def delete_event(event_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `events` WHERE id = %s", (event_id,))
    conn.commit()
    cursor.close()
    conn.close()


# ── Activities & Tasks ─────────────────────────────────────────────────────────

ACTIVITY_PRIORITIES = ["low", "medium", "high", "urgent"]
TASK_STATUSES = ["To Do", "In Progress", "Done"]


def _ensure_activities_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `activities` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            title       VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            start_date  DATE NOT NULL,
            end_date    DATE NOT NULL,
            priority    ENUM('low','medium','high','urgent') NOT NULL DEFAULT 'medium',
            created_by  VARCHAR(100) NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'activities' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_activity_creator'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `activities` ADD CONSTRAINT `fk_activity_creator` "
                "FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            if e.errno != 1826:
                raise


def _ensure_tasks_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `tasks` (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            activity_id INT NOT NULL,
            title       VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            start_date  DATE NOT NULL,
            end_date    DATE NOT NULL,
            priority    ENUM('low','medium','high','urgent') NOT NULL DEFAULT 'medium',
            status      ENUM('To Do','In Progress','Done') NOT NULL DEFAULT 'To Do',
            created_by  VARCHAR(100) NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX (activity_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `task_assignees` (
            task_id  INT NOT NULL,
            username VARCHAR(100) NOT NULL,
            PRIMARY KEY (task_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for table, fk_name, ddl in [
        ("tasks", "fk_task_activity",
         "ALTER TABLE `tasks` ADD CONSTRAINT `fk_task_activity` "
         "FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE"),
        ("tasks", "fk_task_creator",
         "ALTER TABLE `tasks` ADD CONSTRAINT `fk_task_creator` "
         "FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
        ("task_assignees", "fk_task_assignee_task",
         "ALTER TABLE `task_assignees` ADD CONSTRAINT `fk_task_assignee_task` "
         "FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE"),
        ("task_assignees", "fk_task_assignee_user",
         "ALTER TABLE `task_assignees` ADD CONSTRAINT `fk_task_assignee_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = %s "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (table, fk_name),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_activities():
    """Create the activities + tasks + task_assignees tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_activities_table(cursor)
    _ensure_tasks_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def create_activity(title: str, description: str, start_date, end_date, priority: str, created_by: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `activities` (title, description, start_date, end_date, priority, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (title, description, start_date, end_date, priority, created_by),
    )
    activity_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return activity_id


def get_activity(activity_id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `activities` WHERE id = %s", (activity_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def list_activities_for_user(username: str, is_admin: bool = False) -> list[dict]:
    """Activities visible to this user: ones they created, or ones containing
    at least one task assigned to them (admins see all), each annotated with
    task_count/done_count/completion_rate."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT DISTINCT act.* FROM `activities` act "
        "LEFT JOIN `tasks` t ON t.activity_id = act.id "
        "LEFT JOIN `task_assignees` ta ON ta.task_id = t.id "
        "WHERE (%s OR act.created_by = %s OR ta.username = %s) "
        "ORDER BY act.created_at DESC",
        (1 if is_admin else 0, username, username),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if rows:
        activity_ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(activity_ids))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT activity_id, COUNT(*) AS task_count, "
            f"SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done_count "
            f"FROM `tasks` WHERE activity_id IN ({placeholders}) GROUP BY activity_id",
            activity_ids,
        )
        stats_by_activity = {r["activity_id"]: r for r in cursor.fetchall()}
        cursor.close()
        conn.close()
        for r in rows:
            stats = stats_by_activity.get(r["id"])
            task_count = stats["task_count"] if stats else 0
            done_count = stats["done_count"] if stats else 0
            r["task_count"] = task_count
            r["done_count"] = done_count
            r["completion_rate"] = round(100 * done_count / task_count) if task_count else 0

    return rows


def update_activity(activity_id, title: str, description: str, start_date, end_date, priority: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `activities` SET title=%s, description=%s, start_date=%s, end_date=%s, priority=%s WHERE id=%s",
        (title, description, start_date, end_date, priority, activity_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_activity(activity_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `activities` WHERE id = %s", (activity_id,))
    conn.commit()
    cursor.close()
    conn.close()


def _set_task_assignees(cursor, task_id, assignee_usernames):
    cursor.execute("DELETE FROM `task_assignees` WHERE task_id = %s", (task_id,))
    if assignee_usernames:
        cursor.executemany(
            "INSERT IGNORE INTO `task_assignees` (task_id, username) VALUES (%s, %s)",
            [(task_id, u) for u in set(assignee_usernames)],
        )


def create_task(
    activity_id, title: str, description: str, start_date, end_date, priority: str,
    created_by: str, assignee_usernames: list[str] | None = None,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `tasks` (activity_id, title, description, start_date, end_date, priority, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (activity_id, title, description, start_date, end_date, priority, created_by),
    )
    task_id = cursor.lastrowid
    _set_task_assignees(cursor, task_id, assignee_usernames)
    conn.commit()
    cursor.close()
    conn.close()
    return task_id


def get_task(task_id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `tasks` WHERE id = %s", (task_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def list_task_assignees(task_id) -> list[dict]:
    """Assignees of a task, with display-name fields, alphabetical."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT u.username, u.other_names, u.surname, u.position, u.role "
        "FROM `task_assignees` a JOIN `users` u ON u.username = a.username "
        "WHERE a.task_id = %s ORDER BY u.other_names, u.surname",
        (task_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def list_tasks_for_activity_and_user(activity_id, username: str, is_admin: bool = False) -> list[dict]:
    """Tasks in this activity visible to `username`: all of them if they're an
    admin or the activity's creator, otherwise only tasks they're assigned to.
    Each row is annotated with its assignee usernames."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT DISTINCT t.* FROM `tasks` t "
        "JOIN `activities` act ON act.id = t.activity_id "
        "LEFT JOIN `task_assignees` ta ON ta.task_id = t.id "
        "WHERE t.activity_id = %s AND (%s OR act.created_by = %s OR ta.username = %s) "
        "ORDER BY t.start_date, t.id",
        (activity_id, 1 if is_admin else 0, username, username),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if rows:
        task_ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(task_ids))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT task_id, username FROM `task_assignees` WHERE task_id IN ({placeholders})",
            task_ids,
        )
        assignees_by_task: dict[int, list[str]] = {}
        for r in cursor.fetchall():
            assignees_by_task.setdefault(r["task_id"], []).append(r["username"])
        cursor.close()
        conn.close()
        for r in rows:
            r["assignees"] = assignees_by_task.get(r["id"], [])

    return rows


def update_task(
    task_id, title: str, description: str, start_date, end_date, priority: str,
    assignee_usernames: list[str] | None = None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `tasks` SET title=%s, description=%s, start_date=%s, end_date=%s, priority=%s WHERE id=%s",
        (title, description, start_date, end_date, priority, task_id),
    )
    _set_task_assignees(cursor, task_id, assignee_usernames)
    conn.commit()
    cursor.close()
    conn.close()


def update_task_status(task_id, status: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE `tasks` SET status=%s WHERE id=%s", (status, task_id))
    conn.commit()
    cursor.close()
    conn.close()


def delete_task(task_id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `tasks` WHERE id = %s", (task_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    
    
    # ── Feed posts (organization-wide social feed) ──────────────────────────────
# Mirrors the applicant_documents / campaign_location_media pattern: rows in
# `feed_posts` are the posts themselves, images live as separate rows in
# `feed_post_images` (files on disk under FEED_IMAGES_DIR/<post_id>/), and
# `feed_post_likes` / `feed_post_comments` are simple child tables keyed on
# post_id so a post can be liked/commented on by many users.

def _ensure_feed_posts_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `feed_posts` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            author_username   VARCHAR(100) NOT NULL,
            message           TEXT NOT NULL,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    cursor.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE table_schema = DATABASE() AND table_name = 'feed_posts' "
        "AND constraint_type = 'FOREIGN KEY' AND constraint_name = 'fk_feed_post_author'"
    )
    if not cursor.fetchone():
        try:
            cursor.execute(
                "ALTER TABLE `feed_posts` ADD CONSTRAINT `fk_feed_post_author` "
                "FOREIGN KEY (author_username) REFERENCES users(username) "
                "ON DELETE CASCADE ON UPDATE CASCADE"
            )
        except mysql.connector.Error as e:
            # 1826 = duplicate FK constraint name: another concurrent caller
            # already added it between our check and this ALTER.
            if e.errno != 1826:
                raise


def _ensure_feed_post_images_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `feed_post_images` (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            post_id           INT NOT NULL,
            filename          VARCHAR(512) NOT NULL,
            original_filename VARCHAR(255),
            uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (post_id),
            FOREIGN KEY (post_id) REFERENCES feed_posts(id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)


def _ensure_feed_post_likes_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `feed_post_likes` (
            post_id    INT NOT NULL,
            username   VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (post_id, username)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_feed_like_post",
         "ALTER TABLE `feed_post_likes` ADD CONSTRAINT `fk_feed_like_post` "
         "FOREIGN KEY (post_id) REFERENCES feed_posts(id) ON DELETE CASCADE"),
        ("fk_feed_like_user",
         "ALTER TABLE `feed_post_likes` ADD CONSTRAINT `fk_feed_like_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'feed_post_likes' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def _ensure_feed_post_comments_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS `feed_post_comments` (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            post_id    INT NOT NULL,
            username   VARCHAR(100) NOT NULL,
            comment    TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX (post_id, created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
    """)
    for fk_name, ddl in [
        ("fk_feed_comment_post",
         "ALTER TABLE `feed_post_comments` ADD CONSTRAINT `fk_feed_comment_post` "
         "FOREIGN KEY (post_id) REFERENCES feed_posts(id) ON DELETE CASCADE"),
        ("fk_feed_comment_user",
         "ALTER TABLE `feed_post_comments` ADD CONSTRAINT `fk_feed_comment_user` "
         "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE ON UPDATE CASCADE"),
    ]:
        cursor.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE table_schema = DATABASE() AND table_name = 'feed_post_comments' "
            "AND constraint_type = 'FOREIGN KEY' AND constraint_name = %s",
            (fk_name,),
        )
        if not cursor.fetchone():
            try:
                cursor.execute(ddl)
            except mysql.connector.Error as e:
                if e.errno != 1826:
                    raise


def init_feed():
    """Create the feed_posts, feed_post_images, feed_post_likes, and
    feed_post_comments tables (depend on users)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_feed_posts_table(cursor)
    _ensure_feed_post_images_table(cursor)
    _ensure_feed_post_likes_table(cursor)
    _ensure_feed_post_comments_table(cursor)
    conn.commit()
    cursor.close()
    conn.close()


def create_feed_post(author_username: str, message: str) -> int:
    """Create a feed post and return its new id. Attach any images afterward
    via save_feed_post_image_file() + add_feed_post_image()."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_feed_posts_table(cursor)
    cursor.execute(
        "INSERT INTO `feed_posts` (author_username, message) VALUES (%s, %s)",
        (author_username, message),
    )
    conn.commit()
    post_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return post_id


def get_feed_post(id) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_feed_posts_table(cursor)
    cursor.execute(
        "SELECT p.*, u.other_names, u.surname, u.position "
        "FROM `feed_posts` p JOIN `users` u ON u.username = p.author_username "
        "WHERE p.id = %s",
        (id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def list_feed_posts(
    limit: int | None = None, offset: int = 0, viewer_username: str | None = None,
) -> list[dict]:
    """Recent posts, newest first, each annotated with author display fields
    (other_names/surname/position), its images, its like_count, its
    comment_count, and -- if viewer_username is given -- whether the viewer
    has liked it (liked_by_viewer)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = (
        "SELECT p.*, u.other_names, u.surname, u.position "
        "FROM `feed_posts` p JOIN `users` u ON u.username = p.author_username "
        "ORDER BY p.created_at DESC"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params = (limit, offset)
    cursor.execute(query, params)
    posts = cursor.fetchall()
    cursor.close()
    conn.close()

    if not posts:
        return posts

    post_ids = [p["id"] for p in posts]
    placeholders = ",".join(["%s"] * len(post_ids))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        f"SELECT * FROM `feed_post_images` WHERE post_id IN ({placeholders}) ORDER BY id",
        post_ids,
    )
    images_by_post: dict[int, list[dict]] = {}
    for row in cursor.fetchall():
        images_by_post.setdefault(row["post_id"], []).append(row)

    cursor.execute(
        f"SELECT post_id, COUNT(*) AS n FROM `feed_post_likes` "
        f"WHERE post_id IN ({placeholders}) GROUP BY post_id",
        post_ids,
    )
    like_counts = {r["post_id"]: r["n"] for r in cursor.fetchall()}

    cursor.execute(
        f"SELECT post_id, COUNT(*) AS n FROM `feed_post_comments` "
        f"WHERE post_id IN ({placeholders}) GROUP BY post_id",
        post_ids,
    )
    comment_counts = {r["post_id"]: r["n"] for r in cursor.fetchall()}

    liked_by_viewer: set[int] = set()
    if viewer_username:
        cursor.execute(
            f"SELECT post_id FROM `feed_post_likes` "
            f"WHERE post_id IN ({placeholders}) AND username = %s",
            (*post_ids, viewer_username),
        )
        liked_by_viewer = {r["post_id"] for r in cursor.fetchall()}

    cursor.close()
    conn.close()

    for p in posts:
        p["images"] = images_by_post.get(p["id"], [])
        p["like_count"] = like_counts.get(p["id"], 0)
        p["comment_count"] = comment_counts.get(p["id"], 0)
        p["liked_by_viewer"] = p["id"] in liked_by_viewer

    return posts


def count_feed_posts() -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_feed_posts_table(cursor)
    cursor.execute("SELECT COUNT(*) FROM `feed_posts`")
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def update_feed_post(id, message: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `feed_posts` SET message = %s WHERE id = %s",
        (message, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_feed_post(id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT filename FROM `feed_post_images` WHERE post_id = %s", (id,))
    image_files = [r["filename"] for r in cursor.fetchall()]
    for fname in image_files:
        if cloudinary_storage.is_remote_ref(fname):
            cloudinary_storage.destroy(fname)
        else:
            (FEED_IMAGES_DIR / str(id) / fname).unlink(missing_ok=True)

    # `feed_post_images`, `feed_post_likes`, and `feed_post_comments` rows are
    # removed automatically via ON DELETE CASCADE.
    cursor.execute("DELETE FROM `feed_posts` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    try:
        (FEED_IMAGES_DIR / str(id)).rmdir()
    except OSError:
        pass


# ── Feed post images ─────────────────────────────────────────────────────────

def save_feed_post_image_file(post_id, original_filename: str, file_bytes: bytes) -> str:
    """Upload to Cloudinary if configured; otherwise write uploaded bytes
    under FEED_IMAGES_DIR/<post_id>/. Returns either the Cloudinary URL or
    the unique stored filename (safe for the filesystem, collision-free)."""
    safe_name = os.path.basename(original_filename).replace("/", "_").replace("\\", "_")
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    remote_url = cloudinary_storage.upload(file_bytes, folder=f"razetally/feed_images/{post_id}", public_id=stored_name)
    if remote_url:
        return remote_url
    post_dir = FEED_IMAGES_DIR / str(post_id)
    post_dir.mkdir(parents=True, exist_ok=True)
    (post_dir / stored_name).write_bytes(file_bytes)
    return stored_name


def add_feed_post_image(post_id, filename: str, original_filename: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO `feed_post_images` (post_id, filename, original_filename) VALUES (%s, %s, %s)",
        (post_id, filename, original_filename),
    )
    conn.commit()
    image_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return image_id


def list_feed_post_images(post_id) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM `feed_post_images` WHERE post_id = %s ORDER BY id", (post_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_feed_post_image(image_id: int) -> dict | None:
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM `feed_post_images` WHERE id = %s", (image_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_feed_post_image_bytes(image_id: int) -> tuple[bytes, str] | None:
    """Return (file_bytes, display_filename) for download, or None if missing."""
    row = get_feed_post_image(image_id)
    if not row:
        return None
    display_name = row["original_filename"] or row["filename"]
    if cloudinary_storage.is_remote_ref(row["filename"]):
        data = cloudinary_storage.fetch_bytes(row["filename"])
        return (data, display_name) if data is not None else None
    path = FEED_IMAGES_DIR / str(row["post_id"]) / row["filename"]
    if not path.exists():
        return None
    return path.read_bytes(), display_name


# ── Feed post likes ──────────────────────────────────────────────────────────

def toggle_feed_post_like(post_id, username: str) -> bool:
    """Like the post if `username` hasn't liked it yet, otherwise unlike it.
    Returns the resulting liked state (True = now liked)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_feed_post_likes_table(cursor)
    cursor.execute(
        "SELECT 1 FROM `feed_post_likes` WHERE post_id = %s AND username = %s",
        (post_id, username),
    )
    already_liked = cursor.fetchone() is not None
    if already_liked:
        cursor.execute(
            "DELETE FROM `feed_post_likes` WHERE post_id = %s AND username = %s",
            (post_id, username),
        )
    else:
        cursor.execute(
            "INSERT IGNORE INTO `feed_post_likes` (post_id, username) VALUES (%s, %s)",
            (post_id, username),
        )
    conn.commit()
    cursor.close()
    conn.close()
    return not already_liked


def list_feed_post_likes(post_id) -> list[dict]:
    """Users who liked a post, with display-name fields, most recent first."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT l.username, l.created_at, u.other_names, u.surname "
        "FROM `feed_post_likes` l JOIN `users` u ON u.username = l.username "
        "WHERE l.post_id = %s ORDER BY l.created_at DESC",
        (post_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ── Feed post comments ───────────────────────────────────────────────────────

def add_feed_post_comment(post_id, username: str, comment: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_feed_post_comments_table(cursor)
    cursor.execute(
        "INSERT INTO `feed_post_comments` (post_id, username, comment) VALUES (%s, %s, %s)",
        (post_id, username, comment),
    )
    conn.commit()
    comment_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return comment_id


def list_feed_post_comments(post_id) -> list[dict]:
    """Comments on a post, oldest first, with the commenter's display-name fields."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT c.*, u.other_names, u.surname "
        "FROM `feed_post_comments` c JOIN `users` u ON u.username = c.username "
        "WHERE c.post_id = %s ORDER BY c.created_at",
        (post_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def update_feed_post_comment(id, comment: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE `feed_post_comments` SET comment = %s WHERE id = %s",
        (comment, id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_feed_post_comment(id) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM `feed_post_comments` WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()