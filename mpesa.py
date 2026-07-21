"""Safaricom Daraja M-Pesa STK Push (Lipa Na M-Pesa Online) integration.

Reads credentials from environment variables:
    MPESA_ENV              "sandbox" (default) or "production"
    MPESA_CONSUMER_KEY      Daraja app consumer key
    MPESA_CONSUMER_SECRET   Daraja app consumer secret
    MPESA_SHORTCODE         Lipa Na M-Pesa online shortcode (sandbox default: 174379)
    MPESA_PASSKEY           Lipa Na M-Pesa online passkey
    MPESA_CALLBACK_URL      Publicly reachable HTTPS URL Safaricom will POST the
                            payment result to (must route to api.py's
                            /contributions/mpesa/callback)
"""

import base64
import os
from datetime import datetime

import requests

_SANDBOX_BASE_URL = "https://sandbox.safaricom.co.ke"
_PRODUCTION_BASE_URL = "https://api.safaricom.co.ke"


class MpesaError(Exception):
    pass


def _base_url() -> str:
    env = os.environ.get("MPESA_ENV", "sandbox").strip().lower()
    return _PRODUCTION_BASE_URL if env == "production" else _SANDBOX_BASE_URL


def _shortcode() -> str:
    return os.environ.get("MPESA_SHORTCODE", "174379")


def normalize_phone(phone: str) -> str:
    """Convert a Kenyan phone number to the 2547XXXXXXXX / 2541XXXXXXXX format
    Safaricom's API requires, accepting common local formats (07.., 01.., +254.., 254..)."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if digits.startswith("254") and len(digits) == 12:
        return digits
    if len(digits) == 9 and digits[0] in ("7", "1"):
        return "254" + digits
    return digits


def get_access_token() -> str:
    key = os.environ.get("MPESA_CONSUMER_KEY", "")
    secret = os.environ.get("MPESA_CONSUMER_SECRET", "")
    if not key or not secret:
        raise MpesaError("M-Pesa is not configured — set MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET.")
    resp = requests.get(
        f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials",
        auth=(key, secret), timeout=30,
    )
    if not resp.ok:
        raise MpesaError(f"Failed to obtain M-Pesa access token: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def _password_and_timestamp() -> tuple[str, str]:
    passkey = os.environ.get("MPESA_PASSKEY", "")
    if not passkey:
        raise MpesaError("M-Pesa is not configured — set MPESA_PASSKEY.")
    shortcode = _shortcode()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(raw.encode()).decode(), timestamp


def stk_push(phone_number: str, amount: int, account_reference: str, transaction_desc: str) -> dict:
    """Initiate an STK push prompt on the contributor's phone. Returns Daraja's
    response dict (MerchantRequestID/CheckoutRequestID) on success. Raises
    MpesaError if M-Pesa isn't configured or the request is rejected."""
    callback_url = os.environ.get("MPESA_CALLBACK_URL", "")
    if not callback_url:
        raise MpesaError("M-Pesa is not configured — set MPESA_CALLBACK_URL.")

    token = get_access_token()
    password, timestamp = _password_and_timestamp()
    shortcode = _shortcode()
    phone = normalize_phone(phone_number)

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        # Daraja hard-limits these to 12 / 13 characters respectively.
        "AccountReference": account_reference[:12],
        "TransactionDesc": transaction_desc[:13],
    }
    resp = requests.post(
        f"{_base_url()}/mpesa/stkpush/v1/processrequest",
        json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30,
    )
    data = resp.json() if resp.content else {}
    if not resp.ok or str(data.get("ResponseCode")) != "0":
        raise MpesaError(data.get("errorMessage") or data.get("ResponseDescription") or resp.text)
    return data
