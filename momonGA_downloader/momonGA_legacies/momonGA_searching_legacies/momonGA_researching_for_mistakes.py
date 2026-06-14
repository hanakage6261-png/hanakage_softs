import os
import re
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(CURRENT_DIR))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_metadata_store import open_metadata_connection, overwrite_work_metadata
from momonGA_searching.momonGA_searching import (
    create_session,
    fetch_page,
    parse,
    print_result,
)


def parse_ids(raw_text: str) -> list[int]:
    ids = []
    for token in re.split(r"[\s,、]+", raw_text.strip()):
        if not token:
            continue
        if token.lower().startswith("mo"):
            token = token[2:]
        if not token.isdigit():
            raise ValueError(f"IDではない入力です: {token}")
        ids.append(int(token))
    return ids


def print_existing_row(connection, work_id: int):
    row = connection.execute(
        """
        SELECT id, title, date, type, pages, status, downloaded, final_url
        FROM works
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
    print(f"再取得ID: {work_id}")
    print_existing_row(connection, work_id)
    print("")

    html, requested_url, final_url = fetch_page(session, work_id)
    data = parse(html, work_id, requested_url, final_url)
    overwrite_work_metadata(connection, data)

    print("更新後の取得結果:")
    print_result(data)
    print("downloaded フラグは既存値を維持しました。")


def main():
    print("momonGA metadata mistake repair")
    print("修正したいIDを入力してください。複数IDは空白・カンマ区切りで入力できます。")
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
                repair_id(connection, session, work_id)

    finally:
        session.close()
        connection.close()


if __name__ == "__main__":
    main()
