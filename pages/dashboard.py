import base64
import mimetypes
import numbers
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

from db import get_db_connection, get_party_logo_bytes, list_candidates
from form_types import FORM_TYPE_MAP, TALLY_CONFIG
from theme import apply_theme

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

st.set_page_config(layout="wide")
apply_theme()

st.markdown(
    "<h3 style='font-size:2.5rem !important; margin:0;'>Dashboard</h3>",
    unsafe_allow_html=True,
)

st.markdown(
    "<h5 style='font-size:2.25rem !important; margin:0;'>Overall Statistics</h5>",
    unsafe_allow_html=True,
)


@contextmanager
def _conn():
    """A fresh, short-lived connection per query — never shared across sessions
    or reruns. mysql-connector connections aren't safe for concurrent use, and a
    single cached connection shared by every visitor was the cause of the
    intermittent freezes."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(table_name):
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        found = cur.fetchone() is not None
        cur.close()
        return found


@st.cache_data(ttl=15)
def _load(table, order_by):
    if not _table_exists(table):
        return pd.DataFrame()
    try:
        with _conn() as conn:
            return pd.read_sql(f"SELECT * FROM `{table}` ORDER BY {order_by}", con=conn)
    except Exception as e:
        st.error(f"Query failed: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=15)
def _summary_stats():
    """Aggregate totals across all existing form tables."""
    total_forms = total_valid_votes = total_registered = total_rejected = 0
    form_types_with_data = 0
    with _conn() as conn:
        for form_type_key, (forms_tbl, _, _) in FORM_TYPE_MAP.items():
            if not _table_exists(forms_tbl):
                continue
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT COUNT(*),
                           COALESCE(SUM(total_valid_votes), 0),
                           COALESCE(SUM(registered_voters), 0),
                           COALESCE(SUM(rejected_ballots), 0)
                    FROM `{forms_tbl}`
                """)
                row = cur.fetchone()
                cur.close()
                if row and row[0]:
                    total_forms       += row[0]
                    total_valid_votes += row[1]
                    total_registered  += row[2]
                    total_rejected    += row[3]
                    form_types_with_data += 1
            except Exception:
                pass
    return {
        "total_forms":        total_forms,
        "form_types":         form_types_with_data,
        "total_valid_votes":  total_valid_votes,
        "total_registered":   total_registered,
        "total_rejected":     total_rejected,
    }


def _fmt(n):
    """Format large numbers with comma separators."""
    if isinstance(n, numbers.Number) and not isinstance(n, bool):
        return f"{int(n):,}"
    return str(n or "0")


def _show_metrics(placeholders, metrics):
    for placeholder, (label, value) in zip(placeholders, metrics):
        placeholder.metric(label, _fmt(value))


@st.cache_data(ttl=15)
def _distinct_values(table, col):
    """Return sorted distinct non-null values of a column."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT DISTINCT `{col}` FROM `{table}` WHERE `{col}` IS NOT NULL ORDER BY `{col}`")
            vals = [r[0] for r in cur.fetchall()]
            cur.close()
            return vals
    except Exception:
        return []


@st.cache_data(ttl=15)
def _form_ids_for_location(forms_table, filter_col, filter_val):
    """form_id list for forms matching a location filter — the votes table has
    no geographic columns of its own, so this is how the Votes tab joins to
    the shared location filter."""
    if not filter_val or not _table_exists(forms_table):
        return []
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT id FROM `{forms_table}` WHERE `{filter_col}` = %s", (filter_val,))
            ids = [r[0] for r in cur.fetchall()]
            cur.close()
            return ids
    except Exception:
        return []


@st.cache_data(ttl=15)
def _form_type_stats(forms_table):
    """Return stats for a single form type's table."""
    if not _table_exists(forms_table):
        return {"forms": 0, "registered": 0, "valid_votes": 0, "rejected": 0}
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT COUNT(*),
                       COALESCE(SUM(registered_voters), 0),
                       COALESCE(SUM(total_valid_votes), 0),
                       COALESCE(SUM(rejected_ballots), 0)
                FROM `{forms_table}`
            """)
            row = cur.fetchone()
            cur.close()
            return {
                "forms":       row[0] or 0,
                "registered":  row[1] or 0,
                "valid_votes": row[2] or 0,
                "rejected":    row[3] or 0,
            }
    except Exception:
        return {"forms": 0, "registered": 0, "valid_votes": 0, "rejected": 0}


@st.cache_data(ttl=15)
def _tally_filter_stats(forms_table, filter_col=None, filter_val=None):
    """Stats from forms_table, optionally scoped to a geographic filter value."""
    if not _table_exists(forms_table):
        return {"forms": 0, "registered": 0, "valid_votes": 0, "rejected": 0}
    try:
        with _conn() as conn:
            cur = conn.cursor()
            if filter_col and filter_val:
                cur.execute(f"""
                    SELECT COUNT(*),
                           COALESCE(SUM(registered_voters), 0),
                           COALESCE(SUM(total_valid_votes), 0),
                           COALESCE(SUM(rejected_ballots), 0)
                    FROM `{forms_table}` WHERE `{filter_col}` = %s
                """, (filter_val,))
            else:
                cur.execute(f"""
                    SELECT COUNT(*),
                           COALESCE(SUM(registered_voters), 0),
                           COALESCE(SUM(total_valid_votes), 0),
                           COALESCE(SUM(rejected_ballots), 0)
                    FROM `{forms_table}`
                """)
            row = cur.fetchone()
            cur.close()
            return {
                "forms":       row[0] or 0,
                "registered":  row[1] or 0,
                "valid_votes": row[2] or 0,
                "rejected":    row[3] or 0,
            }
    except Exception:
        return {"forms": 0, "registered": 0, "valid_votes": 0, "rejected": 0}


@st.cache_data(ttl=15)
def _county_tally(forms_table, votes_table, county):
    try:
        with _conn() as conn:
            return pd.read_sql(f"""
                SELECT cv.candidate_number, cv.candidate_name,
                       SUM(cv.votes)              AS total_votes,
                       SUM(f.registered_voters)   AS total_registered,
                       SUM(f.total_valid_votes)   AS total_valid_votes,
                       SUM(f.rejected_ballots)    AS total_rejected,
                       COUNT(DISTINCT f.id)       AS stations_counted
                FROM `{forms_table}` f
                JOIN `{votes_table}` cv ON cv.form_id = f.id
                WHERE f.county = %(county)s
                GROUP BY cv.candidate_number, cv.candidate_name
                ORDER BY total_votes DESC
            """, con=conn, params={"county": county})
    except Exception as e:
        st.error(f"Query failed: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=15)
def _candidates_by_position(position: str) -> dict:
    """{lowercased candidate name: {party_name, party_id}} for the given elective
    office — lets tally rows (free-text OCR'd candidate_name) opportunistically
    show party affiliation without requiring an exact join key."""
    return {
        c["name"].strip().lower(): {"party_name": c.get("party_name"), "party_id": c.get("party_id")}
        for c in list_candidates(position=position)
        if c.get("name")
    }


@st.cache_data(ttl=60)
def _party_logo_data_uri(party_id) -> str | None:
    if not party_id:
        return None
    result = get_party_logo_bytes(party_id)
    if not result:
        return None
    file_bytes, _ = result
    return f"data:image/png;base64,{base64.b64encode(file_bytes).decode()}"


@st.dialog("View document", width="large")
def _view_document_dialog(row):
    caption = " — ".join(
        str(v) for v in (row.get("form_number"), row.get("polling_station"))
        if pd.notna(v) and str(v).strip()
    )
    if caption:
        st.caption(caption)

    source_file = row.get("source_file")
    if not source_file:
        st.warning("No source file recorded for this form.")
        return

    path = Path(source_file)
    if not path.exists():
        st.error(f"File not found on disk: {source_file}")
        return

    try:
        data = path.read_bytes()
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        b64 = base64.b64encode(data).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            'width="100%" height="750" style="border:none;"></iframe>',
            unsafe_allow_html=True,
        )
    elif suffix in _IMAGE_SUFFIXES:
        st.image(data, use_container_width=True)
    else:
        st.info(f"Preview not supported for '{suffix}' files — use the download button below.")

    st.download_button(
        "⬇ Download original", data, file_name=path.name,
        mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


# Same palette/hash used by the outward-facing site's Avatar component, so a
# candidate's accent color matches across both apps.
_AVATAR_PALETTE = ["#152744", "#1e4a85", "#2471a3", "#0f7a5c", "#8a3b7c", "#b23b3b", "#c17d1f", "#2f7a7a"]


def _color_for(seed: str) -> str:
    h = 0
    for ch in seed:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return _AVATAR_PALETTE[h % len(_AVATAR_PALETTE)]


def _initials(name: str) -> str:
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _tally_progress_bars(df, position: str | None = None):
    if "total_votes" not in df.columns or "candidate_name" not in df.columns:
        return
    ranked = (
        df.groupby(["candidate_number", "candidate_name"], as_index=False)["total_votes"]
        .sum()
        .sort_values("total_votes", ascending=False)
    )
    total = ranked["total_votes"].sum()

    candidates_by_name = _candidates_by_position(position) if position else {}

    # Every line here must be flush-left with no leading whitespace: Streamlit's
    # markdown renderer treats 4+ leading spaces as a code block, which would
    # dump the raw HTML on screen instead of rendering it (only line 1 of an
    # indented block survives as real HTML, giving a broken-looking result).
    cards = []
    for _, row in ranked.iterrows():
        name = row["candidate_name"] or "Unknown"
        votes = int(row["total_votes"] or 0)
        pct = (votes / total * 100) if total else 0
        color = _color_for(name)

        matched = candidates_by_name.get(name.strip().lower())
        party_name = matched.get("party_name") if matched else None
        logo_uri = _party_logo_data_uri(matched.get("party_id")) if matched else None

        if logo_uri:
            avatar_html = f'<img class="tally-bar-avatar tally-bar-logo" src="{logo_uri}" alt="" />'
        else:
            avatar_html = f'<div class="tally-bar-avatar" style="background:{color};">{_initials(name)}</div>'
        party_html = f'<div class="tally-bar-party">{party_name}</div>' if party_name else ""

        cards.append(
            '<div class="tally-bar-card">'
            f'{avatar_html}'
            '<div class="tally-bar-body">'
            f'<div class="tally-bar-name">{name}</div>'
            f'{party_html}'
            '<div class="tally-bar-track">'
            f'<div class="tally-bar-fill" style="width:{pct:.2f}%; background:{color};"></div>'
            "</div>"
            "</div>"
            '<div class="tally-bar-stats">'
            f'<div class="tally-bar-votes">{votes:,}</div>'
            f'<div class="tally-bar-pct">{pct:.1f}%</div>'
            "</div>"
            "</div>"
        )

    style = (
        "<style>"
        ".tally-bars{display:flex;flex-direction:column;gap:0.75rem;margin-top:0.5rem;}"
        ".tally-bar-card{display:flex;align-items:center;gap:1rem;"
        "border:1px solid rgba(128,128,128,0.25);border-radius:12px;padding:0.9rem 1.1rem;}"
        ".tally-bar-avatar{flex:0 0 auto;width:48px;height:48px;border-radius:50%;"
        "display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:1rem;}"
        ".tally-bar-logo{object-fit:contain;background:#fff;border:1px solid rgba(128,128,128,0.25);}"
        ".tally-bar-body{flex:1 1 auto;min-width:0;}"
        ".tally-bar-name{font-weight:600;margin-bottom:0.4rem;}"
        ".tally-bar-party{font-size:0.82rem;color:rgba(128,128,128,0.9);margin:-0.25rem 0 0.4rem;}"
        ".tally-bar-track{width:100%;height:10px;border-radius:6px;"
        "background:rgba(128,128,128,0.2);overflow:hidden;}"
        ".tally-bar-fill{height:100%;border-radius:6px;}"
        ".tally-bar-stats{flex:0 0 auto;text-align:right;}"
        ".tally-bar-votes{font-weight:700;font-size:1.1rem;}"
        ".tally-bar-pct{color:rgba(128,128,128,0.9);font-size:0.85rem;}"
        "</style>"
    )

    st.markdown(
        style + '<div class="tally-bars">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


# ── Summary metric cards ─────────────────────────────────────────────────────
if st.button("🔄 Refresh", help="Clear the cached stats and reload the latest data"):
    _load.clear()
    _summary_stats.clear()
    _distinct_values.clear()
    _form_ids_for_location.clear()
    _form_type_stats.clear()
    _tally_filter_stats.clear()
    _county_tally.clear()

stats = _summary_stats()
c1, c2, c3, c4, c5 = st.columns(5)
summary_placeholders = [col.empty() for col in (c1, c2, c3, c4, c5)]
_show_metrics(
    summary_placeholders,
    [
        ("Forms processed", stats["total_forms"]),
        ("Form types active", f"{stats['form_types']} / {len(FORM_TYPE_MAP)}"),
        ("Registered voters", stats["total_registered"]),
        ("Valid votes counted", stats["total_valid_votes"]),
        ("Rejected ballots", stats["total_rejected"]),
    ],
)

with st.container(key="card_selector"):
    # ── Form type selector ────────────────────────────────────────────────────────
    # Only offer form types that already have at least one processed form —
    # no point picking an office with nothing captured yet.
    available_form_types = [
        ft for ft in FORM_TYPE_MAP if _form_type_stats(FORM_TYPE_MAP[ft][0])["forms"] > 0
    ]
    if not available_form_types:
        st.info("No forms have been processed for any form type yet.")
        st.stop()

    form_type = st.selectbox(
        "Form type",
        options=available_form_types,
        format_func=lambda k: f"{k} — {FORM_TYPE_MAP[k][2]}",
    )

    st.markdown(
        f"<h5 style='font-size:2.25rem !important; margin:0;'>Form {form_type} Statistics</h5>",
        unsafe_allow_html=True,
        )
    forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
    tally_table, group_key_col, group_name_col = TALLY_CONFIG[form_type]

    ft_stats = _form_type_stats(forms_table)
    m1, m2, m3, m4 = st.columns(4)
    form_type_placeholders = [col.empty() for col in (m1, m2, m3, m4)]
    _show_metrics(
        form_type_placeholders,
        [
            ("Forms processed", ft_stats["forms"]),
            ("Registered voters", ft_stats["registered"]),
            ("Valid votes counted", ft_stats["valid_votes"]),
            ("Rejected ballots", ft_stats["rejected"]),
        ],
    )

# Shared location filter — applies to Forms, Votes, and Tally alike. No "All"
# option; always lands on the first available location.
filter_col = group_name_col or "county"
filter_label = filter_col.replace("_", " ").title()
filter_options = _distinct_values(forms_table, filter_col)

with st.container(key="card_tabs"):
    filter_selected = (
        st.selectbox(f"Filter by {filter_label}", filter_options, key=f"location_filter_{form_type}")
        if filter_options else None
    )

    tab_tally, tab_forms, tab_votes = st.tabs(["Tally", "Forms", "Votes"])

    with tab_forms:
        df = _load(forms_table, "created_at DESC")
        if filter_selected:
            df = df[df[filter_col] == filter_selected]

        if not df.empty:
            df = df.reset_index(drop=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

            form_labels = {
                row["id"]: (
                    " — ".join(
                        str(v) for v in (row.get("form_number"), row.get("polling_station"))
                        if pd.notna(v) and str(v).strip()
                    )
                    or f"Form #{row['id']}"
                )
                for _, row in df.iterrows()
            }
            pick_col, btn_col = st.columns([4, 1])
            with pick_col:
                selected_id = st.selectbox(
                    "View a form's source document",
                    options=list(form_labels.keys()),
                    format_func=lambda fid: form_labels[fid],
                    key=f"forms_pick_{form_type}_{filter_selected}",
                )
            with btn_col:
                st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
                if st.button("View", key=f"forms_view_btn_{form_type}_{filter_selected}"):
                    _view_document_dialog(df[df["id"] == selected_id].iloc[0])
        else:
            st.info(f"No forms recorded yet for form type '{form_type}'.")

    with tab_votes:
        df = _load(votes_table, "votes DESC")
        if filter_selected:
            form_ids = _form_ids_for_location(forms_table, filter_col, filter_selected)
            df = df[df["form_id"].isin(form_ids)]
        if not df.empty:
            st.dataframe(
                df, use_container_width=True, hide_index=True,
                column_config={"candidate_name": st.column_config.TextColumn(width="large")},
            )
        else:
            st.info(f"No votes recorded yet for form type '{form_type}'.")

    with tab_tally:
        if not _table_exists(tally_table):
            st.info("No tally data available yet for this form type.")
            st.stop()

        ts = _tally_filter_stats(forms_table, filter_col if filter_selected else None, filter_selected)
        if filter_selected:
            st.markdown(
                f"<h5 style='font-size:2.25rem !important; margin:0;'>{filter_label}: {filter_selected} Statistics</h5>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<h5 style='font-size:2.25rem !important; margin:0;'>No {filter_label} data yet</h5>",
                unsafe_allow_html=True,
            )

        ts1, ts2, ts3, ts4 = st.columns(4)
        tally_placeholders = [col.empty() for col in (ts1, ts2, ts3, ts4)]
        _show_metrics(
            tally_placeholders,
            [
                ("Forms processed", ts["forms"]),
                ("Registered voters", ts["registered"]),
                ("Valid votes counted", ts["valid_votes"]),
                ("Rejected ballots", ts["rejected"]),
            ],
        )

        # ── Load & filter tally data ────────────────────────────────────────
        if group_key_col:
            if filter_selected:
                df_tally = _load(tally_table, "total_votes DESC")
                df_tally = df_tally[df_tally[group_name_col] == filter_selected]
            else:
                df_tally = pd.DataFrame()
        else:
            if filter_selected:
                df_tally = _county_tally(forms_table, votes_table, filter_selected)
            else:
                df_tally = pd.DataFrame()

        if df_tally.empty:
            st.info("No tally data for the selected filter.")
        else:
            _tally_progress_bars(df_tally, position=FORM_TYPE_MAP[form_type][2])
            st.dataframe(
                df_tally, use_container_width=True, hide_index=True,
                column_config={"candidate_name": st.column_config.TextColumn(width="large")},
            )
