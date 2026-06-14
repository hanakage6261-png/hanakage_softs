from __future__ import annotations

import argparse
from copy import deepcopy
import re
import sys
from pathlib import Path
from typing import Sequence

from yt_dlp import YoutubeDL
from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS
from yt_dlp.cookies import CookieLoadError
from yt_dlp.utils import DownloadError

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "pornhub"
DEFAULT_FORMAT = (
    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a][acodec^=mp4a]/"
    "best[ext=mp4][vcodec^=avc1][acodec^=mp4a]/"
    "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "best[ext=mp4]/best"
)
DEFAULT_FORMAT_SORT = (
    "vcodec:h264",
    "lang",
    "quality",
    "res",
    "fps",
    "hdr:12",
    "acodec:aac",
)
DEFAULT_OUTPUT_TEMPLATE = "%(title).180B.%(ext)s"
COLLISION_OUTPUT_TEMPLATE = "%(title).180B [%(id)s].%(ext)s"
DEFAULT_MERGE_CONTAINER = "mp4"
OWNER_FIELDS = (
    "uploader",
    "uploader_id",
    "channel",
    "channel_id",
    "creator",
    "playlist_uploader",
)
COOKIE_BROWSER_PATTERN = re.compile(
    r"""(?x)
    (?P<name>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download video URLs with yt-dlp and optionally require that the "
            "metadata owner matches an expected uploader name."
        ),
        epilog=(
            "Examples:\n"
            "  python pornhub_downloader.py URL --expected-owner MyChannel\n"
            "  python pornhub_downloader.py --url-file urls.txt --cookies-from-browser chrome\n"
            "  python pornhub_downloader.py URL --cookies cookies.txt --dry-run\n"
            "  python pornhub_downloader.py URL --list-formats\n"
            "  python pornhub_downloader.py URL --format-id hls-2126"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more video URLs to download.",
    )
    parser.add_argument(
        "-f",
        "--url-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Read URLs from a text file. Blank lines and lines starting with # are ignored.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=str(DEFAULT_DOWNLOAD_DIR),
        metavar="DIR",
        help=f"Directory where files are saved. Default: {DEFAULT_DOWNLOAD_DIR}",
    )
    parser.add_argument(
        "--expected-owner",
        metavar="NAME",
        help="Only download if uploader or channel metadata matches this owner name.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        "--browser",
        dest="cookies_from_browser",
        metavar="BROWSER[:PROFILE]",
        help=(
            "Load login cookies from a browser profile. Supported browsers: "
            f"{', '.join(sorted(SUPPORTED_BROWSERS))}"
        ),
    )
    parser.add_argument(
        "--cookies",
        metavar="FILE",
        help="Path to a Netscape-format cookies.txt file.",
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        metavar="SELECTOR",
        help=f"yt-dlp format selector. Default: {DEFAULT_FORMAT}",
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List available combined video/audio streams and exit.",
    )
    parser.add_argument(
        "--format-id",
        metavar="ID",
        help="Download a specific stream format_id instead of the automatic selector.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve metadata and ownership filter only. No media is downloaded.",
    )
    parser.add_argument(
        "--write-info-json",
        action="store_true",
        help="Write a .info.json file next to each download.",
    )
    parser.add_argument(
        "--keep-thumbnail-file",
        action="store_true",
        help="Keep the downloaded thumbnail image file after embedding it into the video.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Do not track downloaded URLs in an archive file.",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="Optional proxy URL passed to yt-dlp.",
    )
    args = parser.parse_args(argv)
    args.prompt_for_format = False

    if args.cookies and args.cookies_from_browser:
        parser.error("Use either --cookies or --cookies-from-browser, not both.")

    if args.expected_owner and not normalize_owner_name(args.expected_owner):
        parser.error("--expected-owner must contain at least one letter or number.")

    args.urls = collect_urls(args.urls, args.url_file)
    if not args.urls and argv is not None:
        parser.error("No URLs were provided. Pass URLs directly or use --url-file.")

    return args


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Could not decode URL file: {path}")


def collect_urls(direct_urls: Sequence[str], url_files: Sequence[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw_value: str) -> None:
        value = raw_value.strip()
        if not value or value.startswith("#") or value in seen:
            return
        seen.add(value)
        urls.append(value)

    for url in direct_urls:
        add_url(url)

    for file_name in url_files:
        path = Path(file_name).expanduser()
        if not path.is_file():
            raise SystemExit(f"URL file was not found: {path}")
        for line in read_text_file(path).splitlines():
            add_url(line)

    return urls


def parse_browser_spec(value: str) -> tuple[str, str | None, str | None, str | None]:
    match = COOKIE_BROWSER_PATTERN.fullmatch(value.strip())
    if not match:
        raise SystemExit(
            "Invalid --cookies-from-browser value. Use "
            "BROWSER[:PROFILE] or BROWSER+KEYRING[:PROFILE][::CONTAINER]."
        )

    browser_name, keyring, profile, container = match.group(
        "name",
        "keyring",
        "profile",
        "container",
    )
    browser_name = browser_name.lower()
    if browser_name not in SUPPORTED_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_BROWSERS))
        raise SystemExit(
            f'Unsupported browser "{browser_name}". Supported browsers: {supported}'
        )

    normalized_keyring: str | None = None
    if keyring is not None:
        normalized_keyring = keyring.upper()
        if normalized_keyring not in SUPPORTED_KEYRINGS:
            supported = ", ".join(sorted(SUPPORTED_KEYRINGS))
            raise SystemExit(
                f'Unsupported keyring "{normalized_keyring}". Supported keyrings: {supported}'
            )

    return browser_name, profile, normalized_keyring, container


def normalize_owner_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def build_owner_filter(expected_owner: str | None):
    if not expected_owner:
        return None

    normalized_expected = normalize_owner_name(expected_owner)

    def match_filter(
        info_dict: dict[str, object],
        *,
        incomplete: bool = False,
    ) -> str | None:
        candidates: list[str] = []
        for field_name in OWNER_FIELDS:
            field_value = info_dict.get(field_name)
            if field_value is not None:
                value = str(field_value).strip()
                if value:
                    candidates.append(value)

        if incomplete and not candidates:
            return None

        normalized_candidates = {
            normalize_owner_name(candidate)
            for candidate in candidates
            if normalize_owner_name(candidate)
        }
        if normalized_expected in normalized_candidates:
            return None

        found = ", ".join(candidates) if candidates else "unknown"
        return (
            f"owner mismatch: expected {expected_owner!r}, "
            f"but metadata says {found!r}"
        )

    return match_filter


def resolve_output_dir(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def build_ydl_options(
    args: argparse.Namespace,
    *,
    outtmpl: str = DEFAULT_OUTPUT_TEMPLATE,
) -> tuple[Path, dict[str, object]]:
    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    postprocessors: list[dict[str, object]] = [
        {
            "key": "FFmpegVideoRemuxer",
            "preferedformat": DEFAULT_MERGE_CONTAINER,
        },
        {
            "key": "EmbedThumbnail",
            "already_have_thumbnail": args.keep_thumbnail_file,
        },
    ]

    ydl_options: dict[str, object] = {
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": outtmpl},
        "format": args.format,
        "format_sort": list(DEFAULT_FORMAT_SORT),
        "ignoreerrors": False,
        "noplaylist": True,
        "skip_download": args.dry_run,
        "windowsfilenames": True,
        "writeinfojson": args.write_info_json,
        "writethumbnail": True,
        "match_filter": build_owner_filter(args.expected_owner),
        "continuedl": True,
        "retries": 20,
        "fragment_retries": 50,
        "file_access_retries": 10,
        "extractor_retries": 5,
        "concurrent_fragment_downloads": 1,
        "external_downloader": {"m3u8": "native"},
        "skip_unavailable_fragments": False,
        "merge_output_format": DEFAULT_MERGE_CONTAINER,
        "postprocessors": postprocessors,
    }

    if args.dry_run:
        ydl_options["writethumbnail"] = False
        ydl_options["postprocessors"] = []

    if args.cookies:
        cookie_path = Path(args.cookies).expanduser().resolve()
        if not cookie_path.is_file():
            raise SystemExit(f"Cookie file was not found: {cookie_path}")
        ydl_options["cookiefile"] = str(cookie_path)
    elif args.cookies_from_browser:
        ydl_options["cookiesfrombrowser"] = parse_browser_spec(args.cookies_from_browser)

    if args.proxy:
        ydl_options["proxy"] = args.proxy

    if not args.no_archive and not args.dry_run:
        ydl_options["download_archive"] = str(output_dir / ".download-archive.txt")

    return output_dir, ydl_options


def build_final_output_path(
    ydl: YoutubeDL,
    info_dict: dict[str, object],
    outtmpl: str,
) -> Path:
    filename = Path(ydl.prepare_filename(info_dict, outtmpl=outtmpl))
    expected_suffix = f".{DEFAULT_MERGE_CONTAINER}"
    if filename.suffix.lower() != expected_suffix:
        filename = filename.with_suffix(expected_suffix)
    return filename


def build_probe_options(download_options: dict[str, object]) -> dict[str, object]:
    probe_options = deepcopy(download_options)
    probe_options["skip_download"] = True
    probe_options["writethumbnail"] = False
    probe_options["postprocessors"] = []
    return probe_options


def format_resolution(format_info: dict[str, object]) -> str:
    resolution = format_info.get("resolution")
    if resolution:
        return str(resolution)
    width = format_info.get("width")
    height = format_info.get("height")
    if width and height:
        return f"{width}x{height}"
    return "-"


def format_bitrate(format_info: dict[str, object]) -> str:
    tbr = format_info.get("tbr")
    if tbr is None:
        return "-"
    return f"{float(tbr):.0f}k"


def format_size(format_info: dict[str, object]) -> str:
    size = format_info.get("filesize") or format_info.get("filesize_approx")
    if not size:
        return "-"
    units = ("B", "KiB", "MiB", "GiB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)}{unit}"
    return f"{value:.1f}{unit}"


def truncate_text(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return f"{value[: width - 1]}~"


def collect_selectable_formats(info_dict: dict[str, object]) -> list[dict[str, object]]:
    formats = info_dict.get("formats") or []
    combined_formats = [
        format_info
        for format_info in formats
        if format_info.get("vcodec") not in (None, "none")
        and format_info.get("acodec") not in (None, "none")
    ]
    mp4_like_formats = [
        format_info for format_info in combined_formats if format_info.get("ext") == "mp4"
    ]
    selectable_formats = mp4_like_formats or combined_formats
    return sorted(
        selectable_formats,
        key=lambda format_info: (
            format_info.get("height") or 0,
            format_info.get("tbr") or 0,
            format_info.get("fps") or 0,
            format_info.get("filesize") or format_info.get("filesize_approx") or 0,
        ),
        reverse=True,
    )


def print_available_formats(title: str, selectable_formats: list[dict[str, object]]) -> None:
    print()
    print(f"Available streams for: {title}")
    if not selectable_formats:
        print("  No combined video/audio streams were found.")
        return

    print(
        " No  ID             Res         FPS  Bitrate  Size      Ext   Video        Audio      Proto"
    )
    print(
        " --  -------------  ----------  ---  -------  --------  ----  -----------  ---------  ----------"
    )
    for index, format_info in enumerate(selectable_formats, start=1):
        format_id = truncate_text(str(format_info.get("format_id") or "-"), 13)
        resolution = truncate_text(format_resolution(format_info), 10)
        fps = str(format_info.get("fps") or "-")
        bitrate = format_bitrate(format_info)
        size = format_size(format_info)
        ext = str(format_info.get("ext") or "-")
        vcodec = truncate_text(str(format_info.get("vcodec") or "-"), 11)
        acodec = truncate_text(str(format_info.get("acodec") or "-"), 9)
        protocol = truncate_text(str(format_info.get("protocol") or "-"), 10)
        print(
            f" {index:>2}  {format_id:<13}  {resolution:<10}  {fps:>3}  {bitrate:>7}  "
            f"{size:<8}  {ext:<4}  {vcodec:<11}  {acodec:<9}  {protocol:<10}"
        )


def choose_format_interactively(
    title: str,
    selectable_formats: list[dict[str, object]],
) -> str | None:
    print_available_formats(title, selectable_formats)
    if not selectable_formats:
        return None

    default_format_id = str(selectable_formats[0].get("format_id"))
    while True:
        response = input(
            f"Choose stream number or format_id for '{title}' "
            f"[Enter={default_format_id}]: "
        ).strip()
        if not response:
            return default_format_id
        if response.isdigit():
            index = int(response)
            if 1 <= index <= len(selectable_formats):
                return str(selectable_formats[index - 1].get("format_id"))
        for format_info in selectable_formats:
            if str(format_info.get("format_id")) == response:
                return response
        print("Invalid selection. Enter a listed number, a listed format_id, or press Enter.")


def resolve_download_format(
    args: argparse.Namespace,
    info_dict: dict[str, object],
) -> str:
    selectable_formats = collect_selectable_formats(info_dict)
    title = str(info_dict.get("title") or info_dict.get("id") or "video")
    available_format_ids = {
        str(format_info.get("format_id"))
        for format_info in (info_dict.get("formats") or [])
        if format_info.get("format_id") is not None
    }

    if args.list_formats:
        print_available_formats(title, selectable_formats)
        return ""

    if args.format_id:
        if args.format_id not in available_format_ids:
            raise SystemExit(f"Requested format_id was not found for this URL: {args.format_id}")
        return args.format_id

    if args.prompt_for_format:
        selected_format = choose_format_interactively(title, selectable_formats)
        if selected_format:
            return selected_format

    return args.format


def plan_downloads(
    args: argparse.Namespace,
    download_options: dict[str, object],
) -> list[dict[str, object]]:
    planned_downloads: list[dict[str, object]] = []
    reserved_paths: set[Path] = set()

    with YoutubeDL(build_probe_options(download_options)) as probe:
        for url in args.urls:
            info_dict = probe.extract_info(url, download=False)
            if not info_dict:
                continue

            download_format = resolve_download_format(args, info_dict)
            if args.list_formats:
                continue

            preferred_path = build_final_output_path(
                probe,
                info_dict,
                DEFAULT_OUTPUT_TEMPLATE,
            )
            use_collision_template = preferred_path in reserved_paths or preferred_path.exists()
            selected_template = (
                COLLISION_OUTPUT_TEMPLATE if use_collision_template else DEFAULT_OUTPUT_TEMPLATE
            )
            final_path = build_final_output_path(probe, info_dict, selected_template)
            reserved_paths.add(final_path)
            planned_downloads.append(
                {
                    "url": url,
                    "title": info_dict.get("title") or url,
                    "outtmpl": selected_template,
                    "path": final_path,
                    "download_format": download_format,
                }
            )

    return planned_downloads


def prompt_if_missing(args: argparse.Namespace) -> argparse.Namespace:
    if args.urls:
        return args

    args.prompt_for_format = True
    print("動画URLを入力してください。複数ある場合は1行に1つ、空行で終了します。")
    collected: list[str] = []
    while True:
        value = input("URL: ").strip()
        if not value:
            break
        collected.append(value)

    if not collected:
        raise SystemExit("URLが入力されていないため終了しました。")

    args.urls = collect_urls(collected, [])

    if not args.expected_owner:
        owner = input(
            "自分の投稿だけに絞るならチャンネル名を入力してください。不要なら空欄のままEnter: "
        ).strip()
        if owner:
            args.expected_owner = owner

    if not args.cookies and not args.cookies_from_browser:
        browser = input(
            "ログインが必要ならブラウザ名を入力してください "
            f"({', '.join(sorted(SUPPORTED_BROWSERS))})。不要なら空欄のままEnter: "
        ).strip()
        if browser:
            args.cookies_from_browser = browser

    return args


def print_summary(args: argparse.Namespace, output_dir: Path) -> None:
    print(f"URLs: {len(args.urls)}")
    print(f"Output directory: {output_dir}")
    print(f"Mode: {'metadata check only' if args.dry_run else 'download'}")
    print(f"Format selector: {args.format}")
    print(f"Final container: {DEFAULT_MERGE_CONTAINER}")
    if args.expected_owner:
        print(f"Expected owner: {args.expected_owner}")
    if args.cookies_from_browser:
        print(f"Cookies from browser: {args.cookies_from_browser}")
    elif args.cookies:
        print(f"Cookies file: {Path(args.cookies).expanduser()}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args = prompt_if_missing(args)
    output_dir, ydl_options = build_ydl_options(args)
    print_summary(args, output_dir)

    try:
        planned_downloads = plan_downloads(args, ydl_options)
        if args.list_formats:
            return 0
        if not planned_downloads:
            print("ダウンロード対象を特定できませんでした。", file=sys.stderr)
            return 1
        for plan in planned_downloads:
            print(f"Planned file: {plan['path'].name}")
            print(f"Planned stream: {plan['download_format']}")

        result = 0
        for plan in planned_downloads:
            run_options = deepcopy(ydl_options)
            run_options["format"] = str(plan["download_format"])
            run_options["outtmpl"] = {"default": str(plan["outtmpl"])}
            with YoutubeDL(run_options) as downloader:
                result = max(result, int(downloader.download([str(plan["url"])]) or 0))
    except CookieLoadError:
        print(
            "ログインCookieの読み込みに失敗しました。"
            " ChromeやEdgeを閉じて再実行するか、"
            " --cookies cookies.txt を使ってください。",
            file=sys.stderr,
        )
        return 1
    except DownloadError as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"Unexpected error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
