from __future__ import annotations

import os
import shutil
import tempfile
import zipfile

from momonGA_modules.momonGA_downloader_modules_network.momonGA_downloader_network import download_binary
from momonGA_modules.momonGA_downloader_modules_shared.momonGA_downloader_shared import (
    IMG_URL_TEMPLATE,
    UNKNOWN_PAGE_LIMIT,
    get_unique_path,
    sanitize_filename,
)


def download_image(session, url: str, path: str) -> bool:
    image_bytes = download_binary(
        session,
        url,
        f"画像取得 {os.path.basename(path)}",
        allow_not_found=True,
    )
    if image_bytes is None:
        return False

    with open(path, "wb") as file:
        file.write(image_bytes)
    return True


def download_gallery_images(session, work_id: str, total_pages, temp_dir: str):
    image_paths = []
    reached_gallery_end = False

    if total_pages:
        page_numbers = range(1, total_pages + 1)
    else:
        page_numbers = range(1, UNKNOWN_PAGE_LIMIT + 1)

    for page_number in page_numbers:
        image_url = IMG_URL_TEMPLATE.format(work_id, page_number)
        image_path = os.path.join(temp_dir, f"{page_number:03}.webp")
        image_downloaded = download_image(session, image_url, image_path)

        if not image_downloaded:
            if total_pages:
                raise RuntimeError(
                    f"{page_number}ページ目の画像を取得できませんでした。"
                    "不完全なPDFになるため、この作品は破棄します。"
                )
            reached_gallery_end = True
            break

        image_paths.append(image_path)

        if total_pages:
            print(f"[{page_number} / {total_pages}] ダウンロード完了")
        else:
            print(f"[{page_number}] ダウンロード完了")

    if not image_paths:
        raise RuntimeError("画像を1枚も取得できませんでした。")

    if total_pages and len(image_paths) != total_pages:
        raise RuntimeError("全ページを取得できなかったため、この作品は破棄します。")

    if not total_pages and not reached_gallery_end:
        raise RuntimeError(
            f"ページ数不明のまま {UNKNOWN_PAGE_LIMIT} ページに達しました。"
            "上限に達したため、この作品は破棄します。"
        )

    return image_paths


def build_cbz(image_paths, cbz_path: str):
    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for image_path in image_paths:
            archive.write(image_path, arcname=os.path.basename(image_path))


def process_work(session, save_root: str, work, record_completed_work=None):
    print("\n画像ダウンロード開始")
    print(f"作品名: {work.title}")
    print(f"作者名: {work.author}")
    print(f"作品URL: {work.final_url}")
    if work.total_pages:
        print(f"ページ数: {work.total_pages}ページ")
    else:
        print("ページ数: 作品ページから取得できませんでした")
    if work.updated_at:
        print(f"更新日: {work.updated_at.isoformat()}")
    print("")

    final_archive = None

    with tempfile.TemporaryDirectory(prefix=f"momonGA_{work.work_id}_") as temp_dir:
        images = download_gallery_images(session, work.work_id, work.total_pages, temp_dir)
        safe_title = sanitize_filename(work.title, f"work_{work.work_id}")
        safe_author = sanitize_filename(work.author, "")
        local_archive = os.path.join(temp_dir, f"{safe_title} {work.work_id}.cbz")
        build_cbz(images, local_archive)

        final_archive = get_unique_path(
            os.path.join(save_root, f"[{safe_author}] {safe_title} {work.work_id}.cbz")
        )
        try:
            shutil.move(local_archive, final_archive)
        except Exception:
            if final_archive and os.path.exists(final_archive):
                os.remove(final_archive)
            raise

    if record_completed_work is not None:
        record_completed_work(work)

    print(f"\n保存先: {final_archive}\n")
