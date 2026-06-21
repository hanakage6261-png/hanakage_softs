import os
import sys
from pathlib import Path


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate_dir in (Path(BASE_DIR), *Path(BASE_DIR).parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_joined_view_name = metadata_store.get_joined_view_name
open_metadata_connection = metadata_store.open_metadata_connection


def main():
    raw_bucket = input("ID幅(空Enterで1000): ").strip()
    bucket_size = int(raw_bucket) if raw_bucket.isdigit() and int(raw_bucket) > 0 else 1000

    connection = open_metadata_connection()
    view_name = get_joined_view_name()

    try:
        rows = connection.execute(
            f"""
            SELECT
                (id / ?) * ? AS bucket_start,
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'found' THEN 1 ELSE 0 END) AS found,
                SUM(CASE WHEN downloaded = 1 THEN 1 ELSE 0 END) AS downloaded
            FROM {view_name}
            GROUP BY bucket_start
            ORDER BY bucket_start
            """,
            (bucket_size, bucket_size),
        ).fetchall()

        print("bucket_start - bucket_end | total | found | downloaded")
        for row in rows:
            start = int(row["bucket_start"])
            end = start + bucket_size - 1
            print(
                f"{start:>8} - {end:<8} | "
                f"{row['total']:>6} | {row['found'] or 0:>6} | {row['downloaded'] or 0:>10}"
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
