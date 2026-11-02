"""One-off migration: upload existing local media under docs/ to Cloudinary
and rewrite the DB rows that reference them to point at the new URLs.

Local files already on Cloudinary (their DB column already holds an
https:// URL) are skipped automatically, so this is safe to re-run.

Usage:
    python migrate_to_cloudinary.py                  # migrate everything
    python migrate_to_cloudinary.py --dry-run         # report only, no uploads/writes
    python migrate_to_cloudinary.py --delete-local    # also delete the local
                                                       # file after a successful
                                                       # upload (kept by default)

Requires CLOUDINARY_URL (or CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET) and the
DB_* variables to be set — see .env.example.
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

import cloudinary_storage
from db import (
    APPLICANT_DOCS_DIR,
    CAMPAIGN_BANNERS_DIR,
    CAMPAIGN_MEDIA_DIR,
    CANDIDATE_PHOTOS_DIR,
    FEED_IMAGES_DIR,
    PARTY_LOGOS_DIR,
    USER_DOCS_DIR,
    get_db_connection,
)

# (table, id_column, parent_column, file_column, local_base_dir, cloudinary_folder)
# parent_column gives the subdirectory a file lives under; it's the same as
# id_column for tables where the media lives directly on the entity row
# (parties.logo, candidates.photo, campaign_locations.banner_image).
JOBS = [
    ("user_documents", "id", "username", "filename", USER_DOCS_DIR, "razetally/user_documents"),
    ("applicant_documents", "id", "application_id", "filename", APPLICANT_DOCS_DIR, "razetally/applicant_documents"),
    ("campaign_location_media", "id", "location_id", "filename", CAMPAIGN_MEDIA_DIR, "razetally/campaign_media"),
    ("feed_post_images", "id", "post_id", "filename", FEED_IMAGES_DIR, "razetally/feed_images"),
    ("parties", "id", "id", "logo", PARTY_LOGOS_DIR, "razetally/party_logos"),
    ("candidates", "id", "id", "photo", CANDIDATE_PHOTOS_DIR, "razetally/candidate_photos"),
    ("campaign_locations", "id", "id", "banner_image", CAMPAIGN_BANNERS_DIR, "razetally/campaign_banners"),
]


def migrate_table(conn, table, id_col, parent_col, file_col, base_dir, cloud_folder, dry_run, delete_local):
    cols = f"`{id_col}`" if parent_col == id_col else f"`{id_col}`, `{parent_col}`"
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"SELECT {cols}, `{file_col}` FROM `{table}` WHERE `{file_col}` IS NOT NULL")
    rows = cursor.fetchall()
    cursor.close()

    moved = already_remote = missing = failed = 0
    for row in rows:
        value = row[file_col]
        if not value:
            continue
        if cloudinary_storage.is_remote_ref(value):
            already_remote += 1
            continue

        parent_value = row[parent_col]
        path = base_dir / str(parent_value) / value
        if not path.exists():
            print(f"  [{table}#{row[id_col]}] missing on disk: {path}")
            missing += 1
            continue

        print(f"  [{table}#{row[id_col]}] {path} -> Cloudinary")
        if dry_run:
            moved += 1
            continue

        url = cloudinary_storage.upload(path.read_bytes(), folder=f"{cloud_folder}/{parent_value}", public_id=value)
        if not url:
            print(f"    upload FAILED for {path}")
            failed += 1
            continue

        update_cursor = conn.cursor()
        update_cursor.execute(f"UPDATE `{table}` SET `{file_col}`=%s WHERE `{id_col}`=%s", (url, row[id_col]))
        conn.commit()
        update_cursor.close()
        if delete_local:
            path.unlink(missing_ok=True)
        moved += 1

    return moved, already_remote, missing, failed


def migrate_forms(conn, dry_run, delete_local):
    """Election forms (forms_34a, forms_35a, ...) store an absolute local path
    in source_file rather than a filename under a docs/ subdirectory, so they
    don't fit migrate_table's base_dir/parent/filename layout."""
    from pathlib import Path

    from form_types import FORM_TYPE_MAP

    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    existing = {r[0] for r in cursor.fetchall()}
    cursor.close()

    moved = already_remote = missing = failed = 0
    for forms_table, _, _ in FORM_TYPE_MAP.values():
        if forms_table not in existing:
            continue
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT id, source_file FROM `{forms_table}` WHERE source_file IS NOT NULL")
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            value = row["source_file"]
            if not value:
                continue
            if cloudinary_storage.is_remote_ref(value):
                already_remote += 1
                continue

            path = Path(value)
            if not path.exists():
                print(f"  [{forms_table}#{row['id']}] missing on disk: {path}")
                missing += 1
                continue

            print(f"  [{forms_table}#{row['id']}] {path} -> Cloudinary")
            if dry_run:
                moved += 1
                continue

            url = cloudinary_storage.upload(path.read_bytes(), folder="razetally/forms", public_id=path.name)
            if not url:
                print(f"    upload FAILED for {path}")
                failed += 1
                continue

            update_cursor = conn.cursor()
            update_cursor.execute(f"UPDATE `{forms_table}` SET source_file=%s WHERE id=%s", (url, row["id"]))
            conn.commit()
            update_cursor.close()
            if delete_local:
                path.unlink(missing_ok=True)
            moved += 1

    return moved, already_remote, missing, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would move without uploading or writing to the DB.")
    parser.add_argument("--delete-local", action="store_true", help="Delete the local file after a successful upload (kept by default).")
    args = parser.parse_args()

    if not args.dry_run and not cloudinary_storage.is_configured():
        print(
            "CLOUDINARY_URL (or CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET) is not set — "
            "nothing to migrate to. Set it in .env, or pass --dry-run to just see what's local.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = get_db_connection()
    totals = {"moved": 0, "already_remote": 0, "missing": 0, "failed": 0}
    for table, id_col, parent_col, file_col, base_dir, cloud_folder in JOBS:
        print(f"\n=== {table} ===")
        moved, already_remote, missing, failed = migrate_table(
            conn, table, id_col, parent_col, file_col, base_dir, cloud_folder, args.dry_run, args.delete_local,
        )
        print(f"  moved={moved} already_remote={already_remote} missing_on_disk={missing} upload_failed={failed}")
        totals["moved"] += moved
        totals["already_remote"] += already_remote
        totals["missing"] += missing
        totals["failed"] += failed

    print("\n=== election forms ===")
    moved, already_remote, missing, failed = migrate_forms(conn, args.dry_run, args.delete_local)
    print(f"  moved={moved} already_remote={already_remote} missing_on_disk={missing} upload_failed={failed}")
    totals["moved"] += moved
    totals["already_remote"] += already_remote
    totals["missing"] += missing
    totals["failed"] += failed
    conn.close()

    print(
        f"\nTOTAL: moved={totals['moved']} already_remote={totals['already_remote']} "
        f"missing_on_disk={totals['missing']} upload_failed={totals['failed']}"
    )
    if args.dry_run:
        print("(dry run — nothing was uploaded or written to the DB)")


if __name__ == "__main__":
    main()
