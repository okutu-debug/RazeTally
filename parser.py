"""Vision API clients (Claude, or Gemini for testing) and IEBC form extraction logic."""

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request

from PIL import Image

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-sonnet-4-6"

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"  # override with GEMINI_MODEL env var

CANDIDATES_PROMPT = """You are reading a Kenyan IEBC election results form (polling station level).
Look at the candidate table only. It has numbered rows (1, 2, 3, …) each with a candidate name and a vote count box on the right. The table ends with a row labelled "Total number of valid votes cast" — STOP before that row.
For each numbered candidate row, return the candidate number, their full name, and the integer vote count from their vote box.
Return ONLY a JSON array, nothing else:
[
  {"number": 1, "name": "FULL NAME", "votes": 0},
  ...
]
"""

METADATA_PROMPT = """You are reading a Kenyan IEBC election results form (polling station level).
Extract every field EXCEPT the individual candidate votes (those are handled separately).
Return ONLY valid JSON, nothing else:
{
  "form_type": null,
  "form_number": null,
  "polling_station": null,
  "polling_station_code": null,
  "ward": null,
  "ward_code": null,
  "constituency": null,
  "constituency_code": null,
  "county": null,
  "county_code": null,
  "total_valid_votes": 0,
  "registered_voters": 0,
  "rejected_ballots": 0,
  "objected_rejections": 0,
  "disputed_votes": 0,
  "presiding_officer": null,
  "deputy_presiding_officer": null,
  "date": "DD-MM-YYYY",
  "comments": null
}

Rules:
- form_type is the IEBC form code printed on the form, usually in the header (e.g. "FORM 35A"). Return just the code: "34A", "35A", "36A", "37A", "38A" or "39A". If the code is unreadable, infer it from the elective position the form is for: President = "34A", Member of National Assembly = "35A", Member of County Assembly = "36A", County Governor = "37A", Senator = "38A", County Woman Representative = "39A". Use null only if neither can be determined.
- total_valid_votes comes from the "Total number of valid votes cast" labeled row.
- registered_voters, rejected_ballots, objected_rejections, disputed_votes come from the "Polling Station Counts" table.
- If a field cannot be determined, use null.
- Return ONLY the JSON object, nothing else.
"""


def image_to_base64_jpeg(img: Image.Image, quality: int = 90) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _image_blocks(images: dict[int, Image.Image]) -> list:
    blocks = []
    sorted_pages = sorted(images.items())
    for page_num, img in sorted_pages:
        if len(sorted_pages) > 1:
            blocks.append({"type": "text", "text": f"[Page {page_num}]"})
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_to_base64_jpeg(img),
            },
        })
    return blocks


def claude_request(content: list, api_key: str, max_tokens: int = 2048) -> str:
    payload = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())

    return _clean_json(body["content"][0]["text"])


def _clean_json(raw: str) -> str:
    """Strip markdown fences / surrounding prose so the reply parses as JSON."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    if not (raw.startswith("{") or raw.startswith("[")):
        match = re.search(r"[\[\{][\s\S]*[\]\}]", raw)
        if match:
            raw = match.group(0)
    return raw


def gemini_request(content: list, api_key: str, max_tokens: int = 2048) -> str:
    """Same contract as claude_request(): takes Anthropic-style content blocks
    (text + base64 image), returns the cleaned JSON text of the reply. Used
    when VISION_PROVIDER=gemini — intended for testing on Gemini's free tier."""
    parts = []
    for block in content:
        if block["type"] == "text":
            parts.append({"text": block["text"]})
        elif block["type"] == "image":
            src = block["source"]
            parts.append({"inline_data": {"mime_type": src["media_type"], "data": src["data"]}})

    payload = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            # Newer Gemini models "think" before answering and those tokens
            # count against this limit, so leave generous headroom or the
            # JSON gets cut off.
            "maxOutputTokens": max(max_tokens, 8192),
            "responseMimeType": "application/json",
            "temperature": 0,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        GEMINI_API_URL.format(model=os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL),
        data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )

    # The free tier often answers 503 "high demand" / 429 "rate limit"; those
    # usually clear within seconds, so retry a few times before giving up.
    delays = [3, 8, 15]
    for attempt in range(len(delays) + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 503) and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            # Surface Google's message (bad key, quota hit, ...) instead of
            # just "HTTP Error 429".
            try:
                detail = json.loads(exc.read())["error"]["message"]
            except Exception:
                detail = exc.reason
            raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc

    try:
        text = "".join(p.get("text", "") for p in body["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        reason = (body.get("candidates") or [{}])[0].get("finishReason") or body.get("promptFeedback")
        raise RuntimeError(f"Gemini returned no text (reason: {reason})")
    return _clean_json(text)


def vision_provider() -> str:
    """'anthropic' (default) or 'gemini', from the VISION_PROVIDER env var."""
    return os.environ.get("VISION_PROVIDER", "anthropic").strip().lower()


def get_vision_api_key() -> tuple[str, str]:
    """Return (api_key, env_var_name) for the active vision provider."""
    env_var = "GEMINI_API_KEY" if vision_provider() == "gemini" else "ANTHROPIC_API_KEY"
    return os.environ.get(env_var, ""), env_var


def parse_form_vision(images: dict[int, Image.Image], api_key: str) -> dict:
    """Two-pass vision extraction: candidates then metadata. Uses Claude by
    default, or Gemini when VISION_PROVIDER=gemini."""
    img_blocks = _image_blocks(images)
    vision_request = gemini_request if vision_provider() == "gemini" else claude_request

    print("  Pass 1: extracting candidates...", end=" ", flush=True)
    raw_candidates = vision_request(
        [{"type": "text", "text": CANDIDATES_PROMPT}] + img_blocks, api_key
    )
    try:
        candidates = json.loads(raw_candidates)
    except json.JSONDecodeError:
        raise ValueError(
            "The uploaded file does not appear to be a valid IEBC election results form. "
            "Please check that you selected the correct document."
        )
    print(f"done ({len(candidates)} candidates)")

    print("  Pass 2: extracting metadata...", end=" ", flush=True)
    raw_metadata = vision_request(
        [{"type": "text", "text": METADATA_PROMPT}] + img_blocks, api_key
    )
    try:
        metadata = json.loads(raw_metadata)
    except json.JSONDecodeError:
        raise ValueError(
            "Could not extract form metadata. "
            "Please check that the document is a clear, complete IEBC election results form."
        )
    print("done")

    metadata["candidates"] = candidates
    return metadata