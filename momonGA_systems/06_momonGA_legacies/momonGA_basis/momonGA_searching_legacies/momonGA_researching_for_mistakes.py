import os
import re
import sys
from pathlib import Path


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate_dir in (Path(CURRENT_DIR), *Path(CURRENT_DIR).parents):
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
overwrite_work_metadata = metadata_store.overwrite_work_metadata

metadata_auto_searching = load_module("metadata_auto_searching")
create_session = metadata_auto_searching.create_session
fetch_page = metadata_auto_searching.fetch_page
parse = metadata_auto_searching.parse
print_result = metadata_auto_searching.print_result


def parse_ids(raw_text: str) -> list[int]:
    ids = []
    for token in re.split(r"[\s,]+", raw_text.strip()):
        if not token:
            continue
        if token.lower().startswith("mo"):
            token = token[2:]
        if not token.isdigit():
            raise ValueError(f"IDではない入力です: {token}")
        ids.append(int(token))
    return ids


def print_existing_row(connection, work_id: int):
    view_name = get_joined_view_name()
    row = connection.execute(
        f"""
        SELECT
            id,
            title,
            date,
            type,
            pages,
            status,
            downloaded,
            final_url
        FROM {view_name}
        WHERE id = ?
        """,
        (work_id,),
    ).fetchone()

    if row is None:
        print(f"DB既存値: ID {work_id} は未登録です。")
        return

    print("DB既存値:")
    print(f"  id: {row['id']}")
    print(f"  title: {row['title']}")
    print(f"  date: {row['date']}")
    print(f"  type: {row['type']}")
    print(f"  pages: {row['pages']}")
    print(f"  status: {row['status']}")
    print(f"  downloaded: {row['downloaded']}")
    print(f"  final_url: {row['final_url']}")


def repair_id(connection, session, work_id: int):
    print("=" * 60)
    print(f"補修対象ID: {work_id}")
    print_existing_row(connection, work_id)
    print("")

    html, requested_url, final_url = fetch_page(session, work_id)
    data = parse(html, work_id, requested_url, final_url)
    overwrite_work_metadata(connection, data)

    print("更新後の取得結果:")
    print_result(data)
    print("downloaded フラグは work_state 側の既存値を維持しました。")


def main():
    print("momonGA metadata mistake repair")
    print("補修したいIDを入力してください。複数IDは空白かカンマ区切りで入力できます。")
    print("空Enterで終了します。")

    connection = open_metadata_connection()
    session = create_session()

    try:
        while True:
            raw_text = input("\nID: ").strip()
            if not raw_text:
                break

            try:
                work_ids = parse_ids(raw_text)
            except ValueError as exc:
                print(f"入力エラー: {exc}")
                continue

            for work_id in work_ids:
                try:
                    repair_id(connection, session, work_id)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    print(f"更新失敗: mo{work_id} / {exc}")

    except KeyboardInterrupt:
        print("\n中断しました。")

    finally:
        session.close()
        connection.close()


if __name__ == "__main__":
    main()
