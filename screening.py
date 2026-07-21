"""Applicant document screening: Claude Vision reads an applicant's uploaded
documents and checks them against their position's published job description
(required documents present + minimum qualifications met)."""

import json

from db import (
    APPLICANT_DOCS_DIR,
    get_application,
    get_published_job_description_for_position,
    list_applicant_documents,
    set_application_qualification_reason,
    update_application_stage,
)
from parser import claude_request, image_to_base64_jpeg
from rasterizer import load_pages

SCREENING_PROMPT = """You are screening a job application against a job description's requirements.

POSITION: {position}

JOB DESCRIPTION (responsibilities, minimum qualifications, required skills):
{description}

REQUIRED DOCUMENTS (the applicant must have submitted all of these):
{required_docs}

Below are the {doc_count} document(s) the applicant submitted, each preceded by a
label showing the title they gave it. Carefully read every submitted document.

Match each submitted document against the required document list by its actual
CONTENT, not just its title (e.g. a document titled "ID" that is clearly not an
identity document does not count). Then assess whether the applicant's background,
as shown in their CV/application letter, meets the minimum qualifications stated
above.

Return ONLY this JSON object, nothing else:
{{
  "missing_documents": ["<required document not adequately provided, if any>"],
  "meets_qualifications": true or false,
  "qualifies": true or false,
  "reason": "<one short sentence (under 25 words) explaining the verdict>"
}}

Rules:
- "qualifies" must be false if missing_documents is non-empty OR meets_qualifications is false.
- "reason" must always be filled in, even when qualifies is true (briefly say why they qualify).
- Keep "reason" short and specific, e.g. "Missing National ID copy" or
  "CV shows only KCSE certificate; Diploma is required".
"""


def screen_application(application_id: str, api_key: str) -> dict:
    """Analyze one application's uploaded documents against its position's
    published job description.

    Returns {"qualifies": bool, "reason": str, "missing_documents": list[str]}.
    Raises ValueError for expected/business conditions (no application, no
    published job description) that should be shown to the user as-is.
    """
    application = get_application(application_id)
    if not application:
        raise ValueError("Application not found.")

    position = application.get("position") or ""
    jd = get_published_job_description_for_position(position)
    if not jd:
        raise ValueError(f"No published job description found for position '{position or '—'}'.")

    required_docs = jd.get("attachment_requirements") or []
    docs = list_applicant_documents(application_id)

    if not docs:
        return {
            "qualifies": False,
            "reason": "No documents uploaded.",
            "missing_documents": required_docs,
        }

    content_blocks = []
    for d in docs:
        file_path = APPLICANT_DOCS_DIR / str(application_id) / d["filename"]
        try:
            pages = load_pages(str(file_path), dpi=150)
        except Exception:
            continue
        content_blocks.append({"type": "text", "text": f"[Document: {d['title']}]"})
        for _, img in sorted(pages.items()):
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_to_base64_jpeg(img),
                },
            })

    if not content_blocks:
        return {
            "qualifies": False,
            "reason": "Uploaded documents could not be read.",
            "missing_documents": required_docs,
        }

    prompt = SCREENING_PROMPT.format(
        position=position or "—",
        description=jd.get("description") or "(no description provided)",
        required_docs=", ".join(required_docs) if required_docs else "(none specified)",
        doc_count=len(docs),
    )

    try:
        raw = claude_request([{"type": "text", "text": prompt}] + content_blocks, api_key, max_tokens=512)
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Could not interpret the screening result from Claude.") from exc
    except Exception as exc:
        raise RuntimeError(f"Screening request failed: {exc}") from exc

    return {
        "qualifies": bool(result.get("qualifies")),
        "reason": (result.get("reason") or "").strip() or "Did not meet the job requirements.",
        "missing_documents": result.get("missing_documents") or [],
    }


def apply_screening_result(application_id: str, result: dict) -> None:
    """Persist a screening verdict: move qualifying applicants to Shortlisting,
    otherwise record the short reason they didn't proceed."""
    if result["qualifies"]:
        set_application_qualification_reason(application_id, None)
        update_application_stage(application_id, "shortlisting")
    else:
        set_application_qualification_reason(application_id, result["reason"])
