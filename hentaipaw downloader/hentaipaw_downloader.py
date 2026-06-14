import os
import re
import shutil
import time
from pathlib import Path

import img2pdf
import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HEADERS = {
    "User-Agent":
    (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/136 Safari/537.36"
    )
}


BASE_DIR = (
    Path.home()
    / "Downloads"
    / "hentaipaw_downloaded"
)

TMP_DIR = (
    BASE_DIR
    / "temp"
)


DOWNLOAD_WAIT = 0.3
TIMEOUT = 30


def create_session():

    session = requests.Session()

    retry = Retry(
        total=10,
        connect=10,
        read=10,

        backoff_factor=2,

        status_forcelist=[
            429,
            500,
            502,
            503,
            504
        ]
    )

    adapter = HTTPAdapter(
        max_retries=retry
    )

    session.mount(
        "http://",
        adapter
    )

    session.mount(
        "https://",
        adapter
    )

    session.headers.update(
        HEADERS
    )

    return session


def sanitize_filename(name):

    name = name.replace(
        " - HentaiPaw",
        ""
    )

    name = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        name
    )

    return name.strip()


def get_article_id(url):

    m = re.search(
        r"/articles/(\d+)",
        url
    )

    if not m:

        raise Exception(
            "article_id取得失敗"
        )

    return m.group(1)


def get_title(
    session,
    url
):

    r = session.get(
        url,
        timeout=TIMEOUT
    )

    r.raise_for_status()

    html = r.text

    title = (
        f"article_"
        f"{get_article_id(url)}"
    )

    m = re.search(
        r"<title>(.*?)</title>",
        html,
        re.I | re.S
    )

    if m:

        title = (
            m.group(1)
            .replace(
                "\n",
                ""
            )
            .strip()
        )

    return sanitize_filename(
        title
    )


def download_images(
    session,
    article_id
):

    TMP_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    files = []

    page = 1

    while True:

        img_url = (
            "https://cdn.imagedeliveries.com/"
            f"{article_id}"
            f"/thumbnails/{page}.webp"
        )

        print(
            "確認:",
            page
        )

        success = False

        for attempt in range(5):

            try:

                r = session.get(
                    img_url,
                    stream=True,
                    timeout=TIMEOUT
                )

                if r.status_code != 200:

                    if page > 1:

                        print(
                            "終了ページ:",
                            page
                        )

                        return files

                    raise Exception(
                        "最初のページ取得失敗"
                    )

                path = (
                    TMP_DIR
                    / f"{page}.webp"
                )

                with open(
                    path,
                    "wb"
                ) as f:

                    for chunk in r.iter_content(
                        8192
                    ):

                        if chunk:

                            f.write(
                                chunk
                            )

                files.append(
                    str(path)
                )

                success = True

                break

            except Exception as e:

                print(
                    f"再試行 {attempt+1}/5:",
                    e
                )

                time.sleep(
                    2
                )

        if not success:

            raise Exception(
                f"{page}ページ取得失敗"
            )

        page += 1

        time.sleep(
            DOWNLOAD_WAIT
        )

    return files


def make_pdf(
    title,
    files
):

    if not files:

        print(
            "画像なし"
        )

        return

    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    out = (
        BASE_DIR
        / f"{title}.pdf"
    )

    counter = 1

    while out.exists():

        out = (
            BASE_DIR
            / (
                f"{title}"
                f" ({counter}).pdf"
            )
        )

        counter += 1

    with open(
        out,
        "wb"
    ) as f:

        f.write(
            img2pdf.convert(
                files
            )
        )

    print(
        "保存:",
        out
    )


def cleanup():

    if TMP_DIR.exists():

        shutil.rmtree(
            TMP_DIR
        )


urls = []

print(
    "・対象サイトURL"
)

print(
    "https://hentaipaw.com/"
)

print()

print("・推奨URL→\nhttps://hentaipaw.com/articles/search?keyword=COMIC+%E5%BF%AB%E6%A5%BD%E5%A4%A9%E3%83%93%E3%83%BC%E3%82%B9%E3%83%88")

print()

print(
    "作品URL入力"
)

print(
    "空Enterで開始"
)


while True:

    x = input(
        "> "
    ).strip()

    if not x:

        break

    urls.append(
        x
    )


BASE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


session = create_session()


for url in urls:

    try:

        article_id = (
            get_article_id(
                url
            )
        )

        title = (
            get_title(
                session,
                url
            )
        )

        print(
            "ID:",
            article_id
        )

        print(
            "TITLE:",
            title
        )

        files = (
            download_images(
                session,
                article_id
            )
        )

        make_pdf(
            title,
            files
        )

    except Exception as e:

        print(
            "ERROR:",
            e
        )

    finally:

        cleanup()


session.close()

print(
    "終了"
)