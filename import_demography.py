"""One-time loader: reads the Kenya demography CSV (county/constituency/ward
hierarchy) and populates the counties/constituencies/wards tables. Safe to
re-run — rows are upserted by their official numeric ID."""

import argparse
import csv
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from db import (
    bulk_upsert_constituencies,
    bulk_upsert_counties,
    bulk_upsert_wards,
    init_demography,
)


def load_csv(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    counties: dict[int, dict] = {}
    constituencies: dict[int, dict] = {}
    wards: list[dict] = []

    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            county_id = int(row["county_id"])
            constituency_id = int(row["constituency_id"])
            ward_name = (row.get("ward_name") or "").strip()

            counties.setdefault(county_id, {
                "county_id": county_id,
                "county_name": row["county_name"].strip(),
            })
            constituencies.setdefault(constituency_id, {
                "constituency_id": constituency_id,
                "constituency_name": row["constituency_name"].strip(),
                "county_id": county_id,
            })
            if ward_name:
                wards.append({
                    "ward_id": int(row["ward_id"]),
                    "ward_name": ward_name,
                    "constituency_id": constituency_id,
                })

    return list(counties.values()), list(constituencies.values()), wards


def main():
    parser = argparse.ArgumentParser(description="Import Kenya demography CSV into MySQL.")
    parser.add_argument("csv_path", help="Path to the demography CSV file.")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"[!] File not found: {csv_path}")
        return

    print("[import_demography] Creating tables if needed...")
    init_demography()

    print(f"[import_demography] Reading {csv_path}...")
    counties, constituencies, wards = load_csv(csv_path)
    print(f"  {len(counties)} counties, {len(constituencies)} constituencies, {len(wards)} wards")

    c_ins, c_upd = bulk_upsert_counties(counties)
    print(f"  Counties:       inserted {c_ins}, updated {c_upd}")

    k_ins, k_upd = bulk_upsert_constituencies(constituencies)
    print(f"  Constituencies: inserted {k_ins}, updated {k_upd}")

    w_ins, w_upd = bulk_upsert_wards(wards)
    print(f"  Wards:          inserted {w_ins}, updated {w_upd}")

    print("[import_demography] Done.")


if __name__ == "__main__":
    main()
