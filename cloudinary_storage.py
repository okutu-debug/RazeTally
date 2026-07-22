"""Optional Cloudinary-backed media storage.

db.py's save_*_file functions try Cloudinary first and fall back to writing
the file to local disk (under docs/, as before) if Cloudinary isn't
configured or the upload fails — so the app works with or without a
Cloudinary account. Files that went to Cloudinary are identified by their
`filename` column holding a full https:// URL instead of a local filename;
`is_remote_ref()` is how callers tell the two apart.
"""

import os
import re
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import requests

_configured: bool | None = None


def _configure() -> bool:
    global _configured
    if _configured is not None:
        return _configured

    url = os.environ.get("CLOUDINARY_URL")
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")

    if url:
        cloudinary.config(cloudinary_url=url, secure=True)
        _configured = True
    elif cloud_name and api_key and api_secret:
        cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)
        _configured = True
    else:
        _configured = False
    return _configured


def is_configured() -> bool:
    return _configure()


def is_remote_ref(value: str | None) -> bool:
    """True if a stored 'filename'/'photo'/'logo' value is a Cloudinary URL
    rather than a local on-disk filename."""
    return bool(value) and value.startswith(("http://", "https://"))


def upload(file_bytes: bytes, folder: str, public_id: str | None = None) -> str | None:
    """Upload bytes to Cloudinary under `folder`. Returns the secure URL on
    success, or None if Cloudinary isn't configured or the upload fails —
    callers should fall back to local disk in that case.

    `public_id` may include a file extension (callers pass the same stored
    filename they'd otherwise write to disk) — it's stripped here since
    Cloudinary appends its own detected-format extension and would
    otherwise double it up (e.g. "...photo.jpg.jpg")."""
    if not _configure():
        print(f"cloudinary_storage.upload: not configured (CLOUDINARY_URL unset?) — falling back to local disk for folder {folder!r}")
        return None
    if public_id:
        public_id = os.path.splitext(public_id)[0]
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            folder=folder,
            public_id=public_id,
            resource_type="auto",
            overwrite=True,
        )
        return result.get("secure_url")
    except Exception as e:
        print(f"cloudinary_storage.upload: failed to upload to folder {folder!r}: {e!r}")
        return None


_UPLOAD_RE = re.compile(r"/(image|video|raw)/upload/(?:v\d+/)?(.+?)(?:\.[^./]+)?$")


def _parse_public_id(url: str) -> tuple[str | None, str]:
    path = urlparse(url).path
    m = _UPLOAD_RE.search(path)
    if not m:
        return None, "image"
    return m.group(2), m.group(1)


def destroy(url: str) -> None:
    """Best-effort delete of a Cloudinary asset given its stored secure URL.
    No-ops silently on failure — DB row deletion should never be blocked by
    an asset cleanup issue."""
    if not is_remote_ref(url) or not _configure():
        return
    public_id, resource_type = _parse_public_id(url)
    if not public_id:
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception as e:
        print(f"cloudinary_storage.destroy: failed to delete {url!r}: {e!r}")


def fetch_bytes(url: str) -> bytes | None:
    """Download a Cloudinary-hosted file's bytes, so existing get_*_bytes
    functions can keep returning (bytes, filename) unchanged regardless of
    where the file actually lives."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"cloudinary_storage.fetch_bytes: failed to fetch {url!r}: {e!r}")
        return None
