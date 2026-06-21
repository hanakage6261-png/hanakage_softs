import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_metadata_store import open_metadata_connection, upsert_work
from momonGA_downloader.momonGA_downloader import (
    create_session,
    dedupe_urls,
    extract_work_urls_from_soup,
    fetch_work_summary,
    get_url_kind,
    iter_collection_pages,
    normalize_url,
    work_to_db_record,
)


def collect_input_urls():
    print("作品URL、作者URL、サークルURL、検索結果URLを入力してください。")
    print("複数入力できます。空Enterで取得を開始します。")
    urls = []

    while True:
        raw_url = input(f"URL {len(urls) + 1}: ").strip()
        if not raw_url:
            return dedupe_urls(urls)
        urls.append(normalize_url(raw_url))


def expand_metadata_urls(session, input_url: str):
    kind = get_url_kind(input_url)
    if kind == "work":
        return [input_url]

    work_urls = []
    for page_number, (page_url, soup) in enumerate(
        iter_collection_pages(session, input_url),
        1,
    ):
        page_urls = extract_work_urls_from_soup(soup, page_url)
        print(f"一覧ページ {page_number}: 作品URL {len(page_urls)} 件")
        work_urls.extend(page_urls)

    return dedupe_urls(work_urls)


def register_metadata(session, connection, work_url: str):
    work = fetch_work_summary(session, work_url)
    upsert_work(connection, work_to_db_record(work))
    print(f"登録: mo{work.work_id} | {work.title}")


def main():
    input_urls = collect_input_urls()
    if not input_urls:
        print("URLが入力されていません。")
        return

    session = create_session()
    connection = open_metadata_connection()
    registered_ids = set()
    failed_urls = []

    try:
        for input_url in input_urls:
            print(f"\n入力URL: {input_url}")
            try:
                work_urls = expand_metadata_urls(session, input_url)
            except Exception as exc:
                print(f"URL展開に失敗しました: {exc}")
                failed_urls.append(input_url)
                continue

            if not work_urls:
                print("作品URLを取得できませんでした。")
                failed_urls.append(input_url)
                continue

            for work_url in work_urls:
                try:
                    work_id = int(work_url.lower().split("mo")[-1].strip("/"))
                except ValueError:
                    work_id = None

                if work_id is not None and work_id in registered_ids:
                    continue

                try:
                    register_metadata(session, connection, work_url)
                    if work_id is not None:
                        registered_ids.add(work_id)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    print(f"登録失敗: {work_url} / {exc}")
                    failed_urls.append(work_url)

    except KeyboardInterrupt:
        print("\n中断しました。")

    finally:
        session.close()
        connection.close()

    print(f"\n登録作品数: {len(registered_ids)}")
    print(f"失敗URL数: {len(failed_urls)}")
    if failed_urls:
        for failed_url in dedupe_urls(failed_urls):
            print(f"- {failed_url}")


if __name__ == "__main__":
    main()
