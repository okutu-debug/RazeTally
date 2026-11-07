"""razetally CLI — OCR-free IEBC Form parser using Claude Vision."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from db import is_already_processed, save_to_db
from form_types import FORM_TYPE_MAP, TALLY_CONFIG, detect_form_type, normalize_form_type
from parser import get_vision_api_key, parse_form_vision
from rasterizer import load_pages


def collect_pdfs(path: Path) -> list[Path]:
    """Return all PDF files under path (directory) or just [path] if it's a file."""
    if path.is_dir():
        return sorted(path.glob("*.pdf"), key=lambda p: p.name.lower())
    return [path]

def process_one(pdf_path: Path, args) -> bool:
    """Process a single PDF. Returns True on success."""
    source_key = str(pdf_path.resolve())

    # Filename prefix is only a hint; the type printed on the form wins (see below).
    filename_type = detect_form_type(pdf_path)

    if args.save_db and not args.force and filename_type and is_already_processed(source_key, filename_type):
        print(f"  [skip] already in DB: {pdf_path.name}")
        return True

    print(f"\n[razetally] {pdf_path.name}  (DPI: {args.dpi})")

    try:
        page_images = load_pages(str(pdf_path), dpi=args.dpi)
    except Exception as e:
        print(f"  [!] Load error: {e}")
        return False

    if args.save_images:
        out_dir = Path(args.save_images) / pdf_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for p, img in page_images.items():
            img.save(out_dir / f"page_{p:03d}.jpg", "JPEG", quality=90)

    print("  [AI] Parsing (2 passes)...")
    try:
        structured = parse_form_vision(page_images, args.api_key)
    except Exception as e:
        print(f"  [!] Parse error: {e}")
        return False

    form_type = normalize_form_type(structured.pop("form_type", None)) or filename_type
    if form_type is None:
        print(f"  [!] Could not determine form type (34A-39A) from the form or filename: {pdf_path.name}")
        return False
    print(f"  Form type: {form_type.upper()} [{FORM_TYPE_MAP[form_type][2]}]")

    if args.save_db and not args.force and form_type != filename_type and is_already_processed(source_key, form_type):
        print(f"  [skip] already in DB: {pdf_path.name}")
        return True

    output_json = json.dumps(structured, indent=2, ensure_ascii=False)

    if args.output:
        out_file = Path(args.output)
        if out_file.is_dir():
            out_file = out_file / f"{pdf_path.stem}.json"
        out_file.write_text(output_json, encoding="utf-8")
        print(f"  [OK] JSON -> {out_file}")
    else:
        print(output_json)

    if args.save_db:
        forms_table, votes_table, _ = FORM_TYPE_MAP[form_type]
        tally_table, _, _ = TALLY_CONFIG[form_type]
        try:
            form_id = save_to_db(structured, source_key, form_type)
            print(f"  [DB] {forms_table} (id={form_id}) + {votes_table} + {tally_table} updated")
        except Exception as e:
            print(f"  [DB] ERROR: {e}")
            return False

    station = structured.get("polling_station", "N/A")
    total   = structured.get("total_valid_votes", "N/A")
    print(f"  [OK] {station} | valid votes: {total}")
    return True

def main():
    import argparse

    parser = argparse.ArgumentParser(description="razetally -- Claude Vision parser for IEBC election result forms")
    parser.add_argument("path", nargs="?", default="docs/forms", help="PDF file or directory of PDFs (default: docs/forms/)", )
    parser.add_argument("--dpi",   type=int, default=300,help="Rasterization DPI (default: 300).")
    parser.add_argument("--output", "-o", help="Save JSON here (file for single, directory for batch).")
    parser.add_argument("--api-key", default=get_vision_api_key()[0], help="Vision API key (default: ANTHROPIC_API_KEY, or GEMINI_API_KEY when VISION_PROVIDER=gemini).")
    parser.add_argument("--save-images", metavar="DIR",help="Save rasterized page images for inspection.")
    parser.add_argument("--save-db", action="store_true",help="Save parsed results to MySQL (uses DB_* env vars).")
    parser.add_argument("--force", action="store_true", help="Re-process files already in the DB (overrides skip).")

    args = parser.parse_args()

    if not args.api_key:
        print(f"[!] No API key found. Set {get_vision_api_key()[1]} or pass --api-key.")
        return

    pdfs = collect_pdfs(Path(args.path))
    if not pdfs:
        print(f"[!] No PDF files found in: {args.path}")
        return

    print(f"\n[razetally] Found {len(pdfs)} PDF(s) in '{args.path}'")
    if args.save_db:
        print(f"            Skip-already-processed: {'OFF (--force)' if args.force else 'ON'}")

    ok = fail = 0
    for pdf in pdfs:
        if process_one(pdf, args):
            ok += 1
        else:
            fail += 1

    print(f"\n{'=' * 60}")
    print(f"Done. Processed: {ok}  Failed: {fail}  (total: {len(pdfs)})")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()