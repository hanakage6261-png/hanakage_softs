import os
import sys
import time
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
open_metadata_connection = metadata_store.open_metadata_connection
overwrite_work_metadata = metadata_store.overwrite_work_metadata
upsert_work = metadata_store.upsert_work

metadata_auto_searching = load_module("metadata_auto_searching")
REQUEST_INTERVAL_SECONDS = metadata_auto_searching.REQUEST_INTERVAL_SECONDS
create_session = metadata_auto_searching.create_session
fetch_page = metadata_auto_searching.fetch_page
load_next_id = metadata_auto_searching.load_next_id
parse = metadata_auto_searching.parse
print_result = metadata_auto_searching.print_result


def ask_limit() -> int | None:
    raw_text = input("今回調査する最大件数を入力してください。空Enterなら全件: ").strip()
    if not raw_text:
        return None
    if not raw_text.isdigit() or int(raw_text) <= 0:
        print("有効な件数ではないため、全件を対象にします。")
        return None
    return int(raw_text)


def iter_not_found_ids(connection, upper_limit_id: int, limit: int | None):
    query = """
        SELECT id
        FROM works
        WHERE id < ?
          AND (status IS NULL OR status != 'found')
        ORDER BY id
    """
    rows = connection.execute(query, (upper_limit_id,))

    count = 0
    for row in rows:
        yield int(row["id"])
        count += 1
        if limit is not None and count >= limit:
            break


def main():
    connection = open_metadata_connection()
    session = create_session()
    upper_limit_id = load_next_id()

    print("momonGA null ID researching")
    print(f"通常巡回の現在ID: {upper_limit_id}")
    print("このID以上は通常巡回を追い越さないため対象外にします。")

    if upper_limit_id <= 0:
        print("通常巡回の進捗が読み取れないため終了します。")
        session.close()
        connection.close()
        return

    limit = ask_limit()
    checked = 0
    found = 0

    try:
        for work_id in iter_not_found_ids(connection, upper_limit_id, limit):
            checked += 1
            html, requested_url, final_url = fetch_page(session, work_id)
            data = parse(html, work_id, requested_url, final_url)

            if data.get("status") == "found":
                overwrite_work_metadata(connection, data)
                found += 1
            else:
                upsert_work(connection, data)

            print_result(data)
            time.sleep(REQUEST_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n中断しました。次回また未発見IDだけを対象にできます。")

    finally:
        session.close()
        connection.close()

    print(f"\n調査件数: {checked}")
    print(f"新たに found になった件数: {found}")


if __name__ == "__main__":
    main()
