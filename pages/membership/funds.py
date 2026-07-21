import os

import streamlit as st

from db import (
    count_contributions,
    create_contribution,
    get_contribution,
    get_contribution_by_paypal_order_id,
    list_contributions,
    set_contribution_mpesa_request,
    set_contribution_paypal_order,
    sum_completed_contributions,
    update_contribution_status,
)
from mpesa import MpesaError, stk_push
from paypal import PayPalError, capture_order, create_order, get_approval_url
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
MPESA_PENDING_KEY = "funds_mpesa_pending_id"
PAYPAL_PENDING_URL_KEY = "funds_paypal_pending_url"
PAYPAL_CONSUMED_KEY = "_funds_paypal_consumed_token"
STATUS_OPTIONS = ["completed", "pending", "failed", "cancelled", "all"]
STATUS_COLORS = {"completed": "#16a34a", "pending": "#d97706", "failed": "#dc2626", "cancelled": "#6b7280"}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Event Funding</h4>",
    unsafe_allow_html=True,
)


def _current_page_url() -> str:
    """Best-effort absolute URL of this page — used to build PayPal's
    return/cancel redirect targets, which must be absolute HTTPS URLs."""
    try:
        url = st.context.url
        if url:
            return url.split("?")[0]
    except Exception:
        pass
    return os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/") + "/funds"


@st.fragment(run_every=3)
def _mpesa_status_panel(contribution_id):
    """Polls the contribution row every few seconds until the M-Pesa callback
    (handled by api.py) has updated its status."""
    contribution = get_contribution(contribution_id)
    if not contribution or contribution["status"] == "pending":
        st.info("⏳ Check your phone and enter your M-Pesa PIN to complete this contribution…")
        if st.button("Cancel", key="mpesa_cancel_wait", use_container_width=True):
            st.session_state[MPESA_PENDING_KEY] = None
            st.rerun()
        return
    if contribution["status"] == "completed":
        st.success(
            f"✅ Received KES {float(contribution['amount']):,.2f} — "
            f"receipt {contribution.get('mpesa_receipt_number') or '—'}"
        )
    else:
        st.error(f"❌ Payment {contribution['status']}: {contribution.get('result_desc') or 'Not completed.'}")
    if st.button("Make another contribution", key="mpesa_reset", use_container_width=True):
        st.session_state[MPESA_PENDING_KEY] = None
        st.rerun()


# ── PayPal return/cancel handling — runs once per redirect, before the rest
# of the page renders ──────────────────────────────────────────────────────
if PAYPAL_CONSUMED_KEY not in st.session_state:
    st.session_state[PAYPAL_CONSUMED_KEY] = None

_paypal_action = st.query_params.get("paypal_action")
_paypal_token = st.query_params.get("token")

if _paypal_action and _paypal_token and st.session_state[PAYPAL_CONSUMED_KEY] != _paypal_token:
    st.session_state[PAYPAL_CONSUMED_KEY] = _paypal_token
    st.session_state[PAYPAL_PENDING_URL_KEY] = None
    contribution = get_contribution_by_paypal_order_id(_paypal_token)
    if contribution:
        if _paypal_action == "return":
            try:
                capture_order(_paypal_token)
                update_contribution_status(contribution["id"], "completed")
                st.session_state["funds_flash"] = ("success", "✅ Thank you! Your PayPal contribution was received.")
            except PayPalError as e:
                update_contribution_status(contribution["id"], "failed", result_desc=str(e))
                st.session_state["funds_flash"] = ("error", f"❌ PayPal payment could not be completed: {e}")
        elif _paypal_action == "cancel":
            update_contribution_status(contribution["id"], "cancelled", result_desc="Cancelled by contributor.")
            st.session_state["funds_flash"] = ("warning", "Payment was cancelled.")
    st.query_params.clear()
    clear_query_params_url()
    st.rerun()

if "funds_flash" in st.session_state:
    _kind, _msg = st.session_state.pop("funds_flash")
    getattr(st, _kind)(_msg)

# ── Totals ────────────────────────────────────────────────────────────────────
with st.container(key="card_funds_stats"):
    _totals = {r["currency"]: r for r in sum_completed_contributions()}
    _kes, _usd = _totals.get("KES"), _totals.get("USD")
    col1, col2, col3 = st.columns(3)
    col1.metric("Raised via M-Pesa", f"KES {float(_kes['total']):,.2f}" if _kes else "KES 0.00")
    col2.metric("Raised via PayPal", f"USD {float(_usd['total']):,.2f}" if _usd else "USD 0.00")
    col3.metric("Completed contributions", (_kes["n"] if _kes else 0) + (_usd["n"] if _usd else 0))

# ── Contribution forms ──────────────────────────────────────────────────────
col_mpesa, col_paypal = st.columns(2)

with col_mpesa:
    with st.container(key="card_mpesa"):
        st.markdown(
            "<h4 style='font-size:1.4rem !important; margin:0 0 0.75rem;'>Contribute via M-Pesa</h4>",
            unsafe_allow_html=True,
        )
        if st.session_state.get(MPESA_PENDING_KEY):
            _mpesa_status_panel(st.session_state[MPESA_PENDING_KEY])
        else:
            with st.form("mpesa_contribute_form", clear_on_submit=True):
                mpesa_name = st.text_input("Full name *", key="mpesa_name")
                mpesa_phone = st.text_input(
                    "M-Pesa phone number *", placeholder="e.g. 0712345678", key="mpesa_phone",
                )
                mpesa_amount = st.number_input(
                    "Amount (KES) *", min_value=1, step=50, value=100, key="mpesa_amount",
                )
                mpesa_submitted = st.form_submit_button(
                    "📲 Send STK Push", type="primary", use_container_width=True,
                )
            if mpesa_submitted:
                if not mpesa_name.strip() or not mpesa_phone.strip():
                    st.error("Full name and phone number are required.")
                else:
                    contribution_id = create_contribution(
                        contributor_name=mpesa_name.strip(), amount=float(mpesa_amount), currency="KES",
                        payment_method="mpesa", phone_number=mpesa_phone.strip(),
                        recorded_by=st.session_state.get("username", ""),
                    )
                    try:
                        result = stk_push(
                            mpesa_phone.strip(), int(mpesa_amount),
                            account_reference=f"CONTRIB{contribution_id}",
                            transaction_desc="Contribution",
                        )
                        set_contribution_mpesa_request(
                            contribution_id,
                            result.get("MerchantRequestID", ""), result.get("CheckoutRequestID", ""),
                        )
                        st.session_state[MPESA_PENDING_KEY] = contribution_id
                        st.rerun()
                    except MpesaError as e:
                        update_contribution_status(contribution_id, "failed", result_desc=str(e))
                        st.error(f"Could not send STK push: {e}")

with col_paypal:
    with st.container(key="card_paypal"):
        st.markdown(
            "<h4 style='font-size:1.4rem !important; margin:0 0 0.75rem;'>Contribute via PayPal</h4>",
            unsafe_allow_html=True,
        )
        pending_url = st.session_state.get(PAYPAL_PENDING_URL_KEY)
        if pending_url:
            st.markdown(
                f'<a href="{pending_url}" target="_top" '
                'style="display:block;text-align:center;padding:0.6rem;border-radius:8px;'
                'background:linear-gradient(160deg,#152744 0%,#1e4a85 55%,#2471a3 100%);'
                'color:white!important;text-decoration:none;font-weight:600;">'
                '💳 Continue to PayPal to complete payment</a>',
                unsafe_allow_html=True,
            )
            if st.button("Cancel / start over", key="paypal_cancel_pending", use_container_width=True):
                st.session_state[PAYPAL_PENDING_URL_KEY] = None
                st.rerun()
        else:
            with st.form("paypal_contribute_form", clear_on_submit=True):
                paypal_name = st.text_input("Full name *", key="paypal_name")
                paypal_email = st.text_input("Email *", key="paypal_email")
                paypal_amount = st.number_input(
                    "Amount (USD) *", min_value=1.0, step=5.0, value=10.0, key="paypal_amount",
                )
                paypal_submitted = st.form_submit_button(
                    "💳 Continue to PayPal", type="primary", use_container_width=True,
                )
            if paypal_submitted:
                if not paypal_name.strip() or not paypal_email.strip():
                    st.error("Full name and email are required.")
                else:
                    contribution_id = create_contribution(
                        contributor_name=paypal_name.strip(), amount=float(paypal_amount), currency="USD",
                        payment_method="paypal", email=paypal_email.strip(),
                        recorded_by=st.session_state.get("username", ""),
                    )
                    page_url = _current_page_url()
                    try:
                        order = create_order(
                            amount=float(paypal_amount), currency="USD",
                            return_url=f"{page_url}?paypal_action=return",
                            cancel_url=f"{page_url}?paypal_action=cancel",
                            reference_id=str(contribution_id),
                            description=f"Contribution from {paypal_name.strip()}",
                        )
                        set_contribution_paypal_order(contribution_id, order["id"])
                        approval_url = get_approval_url(order)
                        if approval_url:
                            st.session_state[PAYPAL_PENDING_URL_KEY] = approval_url
                            st.rerun()
                        else:
                            update_contribution_status(contribution_id, "failed", result_desc="No approval link returned.")
                            st.error("PayPal did not return an approval link. Please try again.")
                    except PayPalError as e:
                        update_contribution_status(contribution_id, "failed", result_desc=str(e))
                        st.error(f"Could not start PayPal checkout: {e}")

# ── Contributors table ──────────────────────────────────────────────────────
with st.container(key="card_contributions"):
    st.markdown(
        "<h4 style='font-size:2.5rem !important; margin:0 0 1rem;'>Contributors</h4>",
        unsafe_allow_html=True,
    )

    if "funds_page" not in st.session_state:
        st.session_state.funds_page = 0

    def _reset_funds_page():
        st.session_state.funds_page = 0

    col_search, col_status = st.columns([3, 1.2])
    search = col_search.text_input(
        "Search", placeholder="Search by name, phone or email",
        label_visibility="collapsed", key="funds_search", on_change=_reset_funds_page,
    )
    status_choice = col_status.selectbox(
        "Status", STATUS_OPTIONS, format_func=lambda s: s.capitalize(),
        label_visibility="collapsed", key="funds_status_filter", on_change=_reset_funds_page,
    )
    status_param = None if status_choice == "all" else status_choice

    total = count_contributions(search, status=status_param)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.funds_page = min(st.session_state.funds_page, total_pages - 1)
    page = st.session_state.funds_page

    rows = list_contributions(search, status=status_param, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not rows:
        st.info("No contributions found.")
    else:
        def _safe(v):
            text = str(v) if v not in (None, "") else "—"
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

        rows_html = ""
        for r in rows:
            contact = r.get("phone_number") or r.get("email") or "—"
            reference = r.get("mpesa_receipt_number") or r.get("paypal_order_id") or "—"
            created = str(r.get("created_at") or "")[:16]
            color = STATUS_COLORS.get(r["status"], "#6b7280")
            rows_html += f"""<tr>
                <td>{_safe(r['contributor_name'])}</td>
                <td>{_safe(r['payment_method'].upper())}</td>
                <td>{float(r['amount']):,.2f} {_safe(r['currency'])}</td>
                <td>{_safe(contact)}</td>
                <td><span style="color:{color};font-weight:600;">{_safe(r['status'].capitalize())}</span></td>
                <td>{_safe(reference)}</td>
                <td>{_safe(created)}</td>
            </tr>"""

        st.html(f"""
        <style>
            .fund-tbl-wrap{{overflow-x:auto;width:100%}}
            .fund-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .fund-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .fund-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:220px;overflow:hidden;text-overflow:ellipsis}}
            .fund-tbl tr:hover td{{background:#f9fafb}}
        </style>
        <div class="fund-tbl-wrap">
            <table class="fund-tbl">
                <thead><tr>
                    <th>Name</th><th>Method</th><th>Amount</th><th>Contact</th>
                    <th>Status</th><th>Reference</th><th>Date</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.funds_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} contribution(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.funds_page += 1
            st.rerun()
