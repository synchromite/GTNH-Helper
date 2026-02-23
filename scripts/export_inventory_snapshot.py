#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.db import connect, connect_profile
from services.mod_sync import write_inventory_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export profile inventory as mod-sync snapshot JSON.")
    parser.add_argument("--content-db", default="gtnh.db", help="Path to content DB (default: gtnh.db)")
    parser.add_argument("--profile-db", default="profile.db", help="Path to profile DB (default: profile.db)")
    parser.add_argument("--out", default="mod_inventory_snapshot.json", help="Output JSON path")
    parser.add_argument(
        "--include-zero-qty",
        action="store_true",
        help="Include inventory rows with only zero quantities",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    content_db = Path(args.content_db)
    profile_db = Path(args.profile_db)
    out_path = Path(args.out)

    content_conn = connect(content_db, read_only=True)
    profile_conn = connect_profile(profile_db)
    try:
        written = write_inventory_snapshot(
            out_path,
            profile_conn,
            content_conn,
            include_zero_qty=bool(args.include_zero_qty),
        )
    finally:
        content_conn.close()
        profile_conn.close()

    print(f"Wrote snapshot: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
