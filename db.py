"""MySQL database helpers: connection, schema creation, save, and tally update."""

import os

import mysql.connector

from form_types import FORM_TYPE_MAP, TALLY_CONFIG


def get_db_connection():
    db_name = os.environ.get("DB_NAME", "tallydb")
    conn = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
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
    """Return True if this file is already saved in its form-type table."""
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


def save_to_db(structured: dict, source_file: str, form_type: str) -> int:
    """Insert parsed results into the correct form-type tables. Returns new form id."""
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_tables(cursor, forms_table, votes_table)

    form_params = {k: v for k, v in structured.items() if k != "candidates"}
    form_params["source_file"] = source_file
    cursor.execute(f"""
        INSERT INTO `{forms_table}` (
            source_file,
            form_number, polling_station, polling_station_code,
            ward, ward_code, constituency, constituency_code,
            county, county_code,
            total_valid_votes, registered_voters, rejected_ballots,
            objected_rejections, disputed_votes,
            presiding_officer, deputy_presiding_officer,
            date, comments
        ) VALUES (
            %(source_file)s,
            %(form_number)s, %(polling_station)s, %(polling_station_code)s,
            %(ward)s, %(ward_code)s, %(constituency)s, %(constituency_code)s,
            %(county)s, %(county_code)s,
            %(total_valid_votes)s, %(registered_voters)s, %(rejected_ballots)s,
            %(objected_rejections)s, %(disputed_votes)s,
            %(presiding_officer)s, %(deputy_presiding_officer)s,
            %(date)s, %(comments)s
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