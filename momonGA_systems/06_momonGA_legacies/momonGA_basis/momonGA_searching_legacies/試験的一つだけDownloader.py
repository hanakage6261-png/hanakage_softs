import requests
from bs4 import BeautifulSoup
import sqlite3
import json

# =========================
# 設定
# =========================
TEST_ID = 850746
BASE_URL = "https://momon-ga.com/fanzine/mo{}/"

DB_NAME = "momon.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

# =========================
# DB初期化
# =========================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS works (
        id INTEGER PRIMARY KEY,
        title TEXT,
        date TEXT,
        type TEXT,
        pages INTEGER,
        parody TEXT,
        circle TEXT,
        author TEXT,
        characters TEXT,
        content TEXT,
        url TEXT,
        status TEXT
    )
    """)

    conn.commit()
    return conn, cursor

# =========================
# 取得処理
# =========================
def fetch_page(id):
    url = BASE_URL.format(id)

    res = requests.get(url, headers=HEADERS)
    res.encoding = res.apparent_encoding

    print("HTTP STATUS:", res.status_code)  # デバッグ用

    return res.text, url

# =========================
# パース処理
# =========================
def parse(html, id, url):
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")

    # 存在判定
    if h1 and "ページが見つかりませんでした" in h1.text:
        return {
            "id": id,
            "status": "not_found"
        }

    # 初期化
    parody = []
    circle = []
    author = []
    characters = []
    content = []

    # 基本情報
    title = h1.text.strip() if h1 else ""
    date = soup.find(id="post-time").text.strip() if soup.find(id="post-time") else ""
    type_ = soup.find(id="post-category").text.strip() if soup.find(id="post-category") else ""

    # ページ数
    pages = None
    page_tag = soup.find(id="post-number")
    if page_tag:
        text = page_tag.text.strip().replace("ページ", "")
        if text.isdigit():
            pages = int(text)

    # タグ系
    tag_tables = soup.find_all(class_="post-tag-table")

    for table in tag_tables:
        title_tag = table.find(class_="post-tag-title")
        if not title_tag:
            continue

        key = title_tag.text.strip()
        tags = [a.text.strip() for a in table.find_all("a")]

        if key == "パロディ":
            parody = tags
        elif key == "サークル":
            circle = tags
        elif key == "作者":
            author = tags
        elif key == "キャラ":
            characters = tags
        elif key == "内容":
            content = tags

    return {
        "id": id,
        "title": title,
        "date": date,
        "type": type_,
        "pages": pages,
        "parody": parody,
        "circle": circle,
        "author": author,
        "characters": characters,
        "content": content,
        "url": url,
        "status": "found"
    }

# =========================
# 保存処理
# =========================
def save(cursor, conn, data):
    cursor.execute("""
    INSERT OR REPLACE INTO works (
        id, title, date, type, pages,
        parody, circle, author, characters, content,
        url, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("id"),
        data.get("title"),
        data.get("date"),
        data.get("type"),
        data.get("pages"),
        json.dumps(data.get("parody", []), ensure_ascii=False),
        json.dumps(data.get("circle", []), ensure_ascii=False),
        json.dumps(data.get("author", []), ensure_ascii=False),
        json.dumps(data.get("characters", []), ensure_ascii=False),
        json.dumps(data.get("content", []), ensure_ascii=False),
        data.get("url"),
        data.get("status")
    ))

    conn.commit()

# =========================
# メイン
# =========================
def main():
    conn, cursor = init_db()

    html, url = fetch_page(TEST_ID)

    # デバッグ確認（必要ならコメント解除）
    # print(html[:500])

    data = parse(html, TEST_ID, url)

    print("=== 取得結果 ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    save(cursor, conn, data)

    print("DBに保存しました")

    conn.close()

if __name__ == "__main__":
    main()