from __future__ import annotations

import mimetypes
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from urllib.request import Request, urlopen


INPUT_FILE = Path(__file__).with_name("ダウンロードリスト.txt")
OUTPUT_DIR_NAME = "H研_download"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HkenDownloader/1.0"
ALLOWED_SCHEMES = {"http", "https"}
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".avif",
}
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}


@dataclass
class Work:
    title: str | None
    urls: list[str]


def resolve_downloads_dir() -> Path:
    candidates = [Path.home() / "Downloads", Path.home() / "ダウンロード"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def parse_manifest(path: Path) -> list[Work]:
    if not path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {path}")

    works: list[Work] = []
    current_title: str | None = None
    current_urls: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_urls
        if current_title or current_urls:
            works.append(Work(title=current_title, urls=current_urls))
        current_title = None
        current_urls = []

    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line:
            flush()
            continue

        if line.startswith("#"):
            continue

        if line.lower().startswith("title:") or line.startswith("タイトル:"):
            if current_urls:
                flush()
            _, title = line.split(":", 1)
            current_title = title.strip() or None
            continue

        if "\t" in line:
            candidate_title, candidate_url = line.split("\t", 1)
            candidate_title = candidate_title.strip()
            candidate_url = candidate_url.strip()
            if looks_like_url(candidate_url):
                if current_urls and current_title not in (None, candidate_title):
                    flush()
                current_title = candidate_title or current_title
                current_urls.append(candidate_url)
                continue

        if not looks_like_url(line):
            raise ValueError(
                f"{line_number}行目がURLとして解釈できません。"
                " `title: 作品名` 行か、`作品名<TAB>画像URL` 行、または画像URL単体で記述してください。"
            )

        current_urls.append(line)

    flush()
    return [work for work in works if work.urls]


def extract_beast_name(title: str | None, fallback_stem: str) -> str:
    source = title or fallback_stem
    match = re.search(r"(\d{4})年\s*(\d{1,2})月", source)
    if match:
        year = match.group(1)
        month = int(match.group(2))
        return f"BEAST {year}年{month}月号"
    return sanitize_filename(source) or "BEAST"


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def infer_extension(url: str, content_type: str | None) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix

    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized in CONTENT_TYPE_EXTENSIONS:
            return CONTENT_TYPE_EXTENSIONS[normalized]
        guessed = mimetypes.guess_extension(normalized)
        if guessed:
            return guessed

    return ".img"


def download_image(url: str, destination: Path) -> Path:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type()
        if not content_type.startswith("image/"):
            raise ValueError(
                f"画像URLではありません: {url} (Content-Type: {content_type})"
            )

        extension = infer_extension(url, content_type)
        final_path = destination.with_suffix(extension)
        with final_path.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle, length=1024 * 64)
        return final_path


def build_cbz(work: Work, output_root: Path) -> Path:
    with TemporaryDirectory(prefix="hken_", dir=output_root) as temp_dir:
        temp_path = Path(temp_dir)
        downloaded_files: list[Path] = []

        for index, url in enumerate(work.urls, start=1):
            base_name = temp_path / f"{index:04d}"
            downloaded = download_image(url, base_name)
            downloaded_files.append(downloaded)
            print(f"  保存: {downloaded.name}")

        if not downloaded_files:
            raise ValueError("画像が1枚も取得できませんでした。")

        fallback_stem = downloaded_files[0].stem
        cbz_name = extract_beast_name(work.title, fallback_stem)
        output_path = unique_path(output_root / f"{cbz_name}.cbz")

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for file_path in downloaded_files:
                archive.write(file_path, arcname=file_path.name)

        return output_path


def main() -> int:
    try:
        works = parse_manifest(INPUT_FILE)
    except Exception as exc:  # noqa: BLE001
        print(f"入力エラー: {exc}", file=sys.stderr)
        return 1

    if not works:
        print("処理対象がありません。", file=sys.stderr)
        return 1

    output_root = resolve_downloads_dir() / OUTPUT_DIR_NAME
    output_root.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for index, work in enumerate(works, start=1):
        title_label = work.title or f"作品{index}"
        print(f"[{index}/{len(works)}] {title_label}")
        try:
            output_path = build_cbz(work, output_root)
        except Exception as exc:  # noqa: BLE001
            print(f"  失敗: {exc}", file=sys.stderr)
            continue

        success_count += 1
        print(f"  完了: {output_path}")

    if success_count == 0:
        print("1件もCBZを作成できませんでした。", file=sys.stderr)
        return 1

    print(f"完了: {success_count}件を保存しました。保存先: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
