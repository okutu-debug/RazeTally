"""Claude Vision API client and Form 35A extraction logic."""

import base64
import io
import json
import re
import urllib.request

from PIL import Image

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-sonnet-4-6"

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


def _claude_request(content: list, api_key: str, max_tokens: int = 2048) -> str:
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

    raw = body["content"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    if not (raw.startswith("{") or raw.startswith("[")):
        match = re.search(r"[\[\{][\s\S]*[\]\}]", raw)
        if match:
            raw = match.group(0)
    return raw


def parse_form_vision(images: dict[int, Image.Image], api_key: str) -> dict:
    """Two-pass Claude Vision extraction: candidates then metadata."""
    img_blocks = _image_blocks(images)

    print("  Pass 1: extracting candidates...", end=" ", flush=True)
    candidates = json.loads(
        _claude_request([{"type": "text", "text": CANDIDATES_PROMPT}] + img_blocks, api_key)
    )
    print(f"done ({len(candidates)} candidates)")

    print("  Pass 2: extracting metadata...", end=" ", flush=True)
    metadata = json.loads(
        _claude_request([{"type": "text", "text": METADATA_PROMPT}] + img_blocks, api_key)
    )
    print("done")

    metadata["candidates"] = candidates
    return metadata