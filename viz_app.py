import os
from pathlib import Path
from typing import Tuple

import pandas as pd
import streamlit as st
import plotly.express as px

from dotenv import load_dotenv
load_dotenv()

from form_types import FORM_TYPE_MAP, TALLY_CONFIG
from db import get_db_connection
from processor import process_pdf, save_upload


def get_table_names(form_type: str) -> Tuple[str, str, str]:
    forms_table, votes_table, human_label = FORM_TYPE_MAP[form_type]
    tally_table, group_key_col, group_name_col = TALLY_CONFIG[form_type]
    return forms_table, votes_table, tally_table


@st.cache_resource
def get_conn():
    return get_db_connection()


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


def load_forms(conn, forms_table: str) -> pd.DataFrame:
    if not _table_exists(conn, forms_table):
        return pd.DataFrame()
    try:
        return pd.read_sql(f"SELECT * FROM `{forms_table}` ORDER BY created_at DESC", con=conn)
    except Exception as e:
        st.error(f"Failed to load forms: {e}")
        return pd.DataFrame()


def load_votes(conn, votes_table: str) -> pd.DataFrame:
    if not _table_exists(conn, votes_table):
        return pd.DataFrame()
    try:
        return pd.read_sql(f"SELECT * FROM `{votes_table}` ORDER BY id DESC", con=conn)
    except Exception as e:
        st.error(f"Failed to load votes: {e}")
        return pd.DataFrame()


def load_tally(conn, tally_table: str) -> pd.DataFrame:
    if not _table_exists(conn, tally_table):
        return pd.DataFrame()
    try:
        return pd.read_sql(f"SELECT * FROM `{tally_table}` ORDER BY total_votes DESC", con=conn)
    except Exception as e:
        st.error(f"Failed to load tally: {e}")
        return pd.DataFrame()


def main():
    st.set_page_config(page_title="RazeTally Viewer", layout="wide")
    st.title("Raze Tally")

    # st.sidebar.header("Connection")
    # st.sidebar.markdown("Reads DB connection from environment variables.\nSet `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.")

    form_type = st.sidebar.selectbox("Select Form Type", options=list(FORM_TYPE_MAP.keys()), format_func=lambda k: f"{k} — {FORM_TYPE_MAP[k][2]}")

    conn = get_conn()
    forms_table, votes_table, tally_table = get_table_names(form_type)

    tab1, tab2, tab3, tab4 = st.tabs(["Forms", "Votes", "Tally", "Upload"])

    with tab1:
        st.subheader("Forms table")
        df_forms = load_forms(conn, forms_table)
        if not df_forms.empty:
            st.dataframe(df_forms)
        else:
            st.info(f"No data yet for form type '{form_type}'. Process some PDFs with `--save-db` first.")

    with tab2:
        st.subheader("Votes table")
        df_votes = load_votes(conn, votes_table)
        if not df_votes.empty:
            st.dataframe(df_votes)
        else:
            st.info(f"No data yet for form type '{form_type}'. Process some PDFs with `--save-db` first.")

    with tab3:
        st.subheader("Tally")
        df_tally = load_tally(conn, tally_table)
        if not df_tally.empty:
            st.dataframe(df_tally)
            # Top candidates chart
            if "total_votes" in df_tally.columns and "candidate_name" in df_tally.columns:
                top_n = st.slider("Top N candidates", min_value=3, max_value=20, value=8)
                df_top = df_tally.groupby(["candidate_number", "candidate_name"], as_index=False)["total_votes"].sum()
                df_top = df_top.sort_values("total_votes", ascending=False).head(top_n)
                fig = px.bar(df_top, x="candidate_name", y="total_votes", color="candidate_name", labels={"total_votes":"Votes", "candidate_name":"Candidate"}, title="Top candidates by total votes")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No tally data available yet for this form type.")

    with tab4:
        st.subheader("Upload a completed form")
        st.caption(
            "Filename must start with the form code, e.g. `F35A-003-017-....pdf`. "
            "Accepted formats: PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP. "
            "The form will be saved to `docs/forms/`, parsed with Claude Vision, and written to the DB."
        )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error("ANTHROPIC_API_KEY is not set — cannot parse uploaded forms.")
        else:
            uploaded = st.file_uploader(
                "Choose a form file",
                type=["pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"],
            )
            force = st.checkbox("Re-process if already in DB", value=False)

            if uploaded and st.button("Process & save to DB", type="primary"):
                dest = save_upload(uploaded.read(), uploaded.name)
                try:
                    with st.spinner(f"Processing {uploaded.name} (this takes ~20 s)…"):
                        result = process_pdf(Path(dest), api_key, force=force)
                    st.success(
                        f"Saved! Form ID {result['form_id']} — "
                        f"{result.get('polling_station', 'N/A')} | "
                        f"valid votes: {result.get('total_valid_votes', 'N/A')}"
                    )
                    candidates = result.get("candidates", [])
                    if candidates:
                        st.dataframe(
                            pd.DataFrame(candidates).rename(
                                columns={"number": "#", "name": "Candidate", "votes": "Votes"}
                            ),
                            use_container_width=True,
                        )
                except (ValueError, RuntimeError) as e:
                    st.error(str(e))


if __name__ == "__main__":
    main()
