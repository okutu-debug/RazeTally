import os
from pathlib import Path

import pandas as pd
import streamlit as st

from parser import get_vision_api_key
from processor import process_pdf, save_upload
from theme import apply_theme

apply_theme()
st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Batch Upload</h4>",
    unsafe_allow_html=True,
)

api_key, api_key_var = get_vision_api_key()
if not api_key:
    st.error(f"{api_key_var} is not set — cannot parse uploaded forms.")
    st.stop()

if "batch_results" not in st.session_state:
    st.session_state.batch_results = None  # list of {"File", "Status", "Detail", "_dest"}
if "batch_upload_key" not in st.session_state:
    st.session_state.batch_upload_key = 0


def _process_one(dest: Path, filename: str, force: bool) -> dict:
    """Run the full parse+save pipeline on an already-saved file and return a
    result row. Shared by the initial batch run and the retry-failed action."""
    try:
        result = process_pdf(
            dest, api_key, force=force, uploaded_by=st.session_state.get("username", ""),
        )
        return {
            "File": filename, "Status": "✅ Saved",
            "Detail": f"Form ID {result['form_id']} — {result.get('polling_station') or 'N/A'}",
            "_dest": dest,
        }
    except (ValueError, RuntimeError) as e:
        return {"File": filename, "Status": "❌ Failed", "Detail": str(e), "_dest": dest}


def _run_batch(jobs: list[tuple[Path, str]], force: bool) -> list[dict]:
    """jobs: [(dest_path, filename), ...]. Shows a progress bar while processing."""
    results = []
    progress = st.progress(0.0)
    status = st.empty()
    for i, (dest, filename) in enumerate(jobs):
        status.caption(f"Processing {filename} ({i + 1}/{len(jobs)})…")
        results.append(_process_one(dest, filename, force))
        progress.progress((i + 1) / len(jobs))
    status.empty()
    progress.empty()
    return results


with st.container(key="card_batch_upload"):
    st.caption(
        "Any filenames work — each form's type (34A–39A) is read from the form itself, "
        "so keep the header visible. Accepted formats: PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP. Every file is extracted "
        "and saved straight to the database — there's no per-file review step like the "
        "single Upload Form page, so double-check scans before uploading a large batch."
    )
    uploaded_files = st.file_uploader(
        "Choose form files",
        type=["pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"],
        accept_multiple_files=True,
        key=f"batch_upload_{st.session_state.batch_upload_key}",
    )
    force = st.checkbox("Re-process if already in DB", value=False)

    if uploaded_files and st.button(f"Process {len(uploaded_files)} file(s)", type="primary"):
        jobs = [(save_upload(f.read(), f.name), f.name) for f in uploaded_files]
        st.session_state.batch_results = _run_batch(jobs, force)
        st.session_state.batch_upload_key += 1
        st.rerun()

if st.session_state.batch_results is not None:
    with st.container(key="card_batch_results"):
        results = st.session_state.batch_results
        failed_indices = [i for i, r in enumerate(results) if r["Status"].startswith("❌")]
        ok = len(results) - len(failed_indices)
        st.markdown(f"**{ok} of {len(results)} file(s) saved successfully.**")
        st.dataframe(
            pd.DataFrame(results).drop(columns="_dest"), use_container_width=True, hide_index=True,
        )

        col_retry, col_clear, _ = st.columns([2, 1.4, 6])
        if failed_indices and col_retry.button(f"🔁 Retry {len(failed_indices)} failed file(s)", type="primary"):
            jobs = [(results[i]["_dest"], results[i]["File"]) for i in failed_indices]
            for i, new_result in zip(failed_indices, _run_batch(jobs, force)):
                results[i] = new_result
            st.session_state.batch_results = results
            st.rerun()
        if col_clear.button("Clear results"):
            st.session_state.batch_results = None
            st.rerun()
