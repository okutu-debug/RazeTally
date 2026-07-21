"""PayPal Orders v2 REST API integration (redirect-based checkout, no JS SDK).

Reads credentials from environment variables:
    PAYPAL_ENV             "sandbox" (default) or "live"
    PAYPAL_CLIENT_ID
    PAYPAL_CLIENT_SECRET
"""

import os

import requests

_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
_LIVE_BASE_URL = "https://api-m.paypal.com"


class PayPalError(Exception):
    pass


def _base_url() -> str:
    env = os.environ.get("PAYPAL_ENV", "sandbox").strip().lower()
    return _LIVE_BASE_URL if env == "live" else _SANDBOX_BASE_URL


def get_access_token() -> str:
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise PayPalError("PayPal is not configured — set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.")
    resp = requests.post(
        f"{_base_url()}/v1/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    if not resp.ok:
        raise PayPalError(f"Failed to obtain PayPal access token: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def create_order(
    amount: float, currency: str, return_url: str, cancel_url: str, reference_id: str,
    description: str = "",
) -> dict:
    """Create a PayPal order for a single payment. The returned dict's `links`
    include an 'approve' URL to send the contributor's browser to — PayPal then
    redirects back to return_url (approved) or cancel_url (cancelled), appending
    its own `token` (order id) query parameter to whichever one it uses."""
    token = get_access_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": reference_id,
            "description": (description or "Campaign contribution")[:127],
            "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
        }],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "PAY_NOW",
            "brand_name": "RazeTally",
        },
    }
    resp = requests.post(
        f"{_base_url()}/v2/checkout/orders",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    data = resp.json() if resp.content else {}
    if not resp.ok:
        raise PayPalError(data.get("message") or resp.text)
    return data


def get_approval_url(order: dict) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") == "approve":
            return link.get("href")
    return None


def capture_order(order_id: str) -> dict:
    """Capture a previously approved order. Returns PayPal's capture response dict."""
    token = get_access_token()
    resp = requests.post(
        f"{_base_url()}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    data = resp.json() if resp.content else {}
    if not resp.ok:
        raise PayPalError(data.get("message") or resp.text)
    return data
