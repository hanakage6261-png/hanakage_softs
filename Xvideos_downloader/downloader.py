#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Sequence

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.cookies import CookieLoadError, SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS
    from yt_dlp.utils import DownloadError
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "yt-dlp is required. Install it with: python -m pip install -U yt-dlp"
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
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
            "Download Xvideos video URLs with yt-dlp. "
            "Use it only for videos that you own or are allowed to download."
        ),
        epilog=(
            "Examples:\n"
            "  python downloader.py \"https://www.xvideos.com/video123456/example\"\n"
            "  python downloader.py --url-file urls.txt --expected-owner MyAccount\n"
            "  python downloader.py URL --cookies-from-browser chrome --dry-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="One or more Xvideos page URLs.",
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
        default="downloads",
        metavar="DIR",
        help="Directory where files are saved. Default: downloads",
    )
    parser.add_argument(
        "--expected-owner",
        metavar="NAME",
        help="Only download when uploader/channel metadata matches this name.",
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
        "--filename",
        metavar="NAME",
        help="Optional output filename for a single URL. The media extension is added automatically.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output file.",
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        metavar="SELECTOR",
        help=f"yt-dlp format selector. Default: {DEFAULT_FORMAT}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve metadata and owner filter only. No media is downloaded.",
    )
    args = parser.parse_args(argv)

    if args.cookies and args.cookies_from_browser:
        parser.error("Use either --cookies or --cookies-from-browser, not both.")

    if args.expected_owner and not normalize_owner_name(args.expected_owner):
        parser.error("--expected-owner must contain at least one letter or number.")

    args.urls = collect_urls(args.urls, args.url_file)

    if args.filename and len(args.urls) > 1:
        parser.error("--filename can only be used when downloading one URL.")

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


def normalize_owner_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def sanitize_filename(value: str) -> str:
    trimmed = Path(value.strip()).name
    cleaned = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in trimmed)
    cleaned = cleaned.strip(" .")
    if cleaned in {"", ".", ".."}:
        raise ValueError("Filename must contain at least one visible character.")
    return cleaned


def validate_xvideos_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Only http/https URLs are supported: {url}")

    hostname = (parsed.hostname or "").strip(".").lower()
    if not hostname:
        raise ValueError(f"Could not determine the hostname: {url}")

    if hostname != "xvideos.com" and not hostname.endswith(".xvideos.com"):
        raise ValueError(f"Only xvideos.com URLs are supported: {url}")


def parse_browser_spec(value: str) -> tuple[str, str | None, str | None, str | None]:
    match = COOKIE_BROWSER_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(
            "Invalid browser spec. Use BROWSER[:PROFILE] or "
            "BROWSER+KEYRING[:PROFILE][::CONTAINER]."
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
        raise ValueError(
            f'Unsupported browser "{browser_name}". Supported browsers: {supported}'
        )

    normalized_keyring: str | None = None
    if keyring is not None:
        normalized_keyring = keyring.upper()
        if normalized_keyring not in SUPPORTED_KEYRINGS:
            supported = ", ".join(sorted(SUPPORTED_KEYRINGS))
            raise ValueError(
                f'Unsupported keyring "{normalized_keyring}". Supported keyrings: {supported}'
            )

    return browser_name, profile, normalized_keyring, container


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


def build_output_template(filename: str | None) -> str:
    if not filename:
        return DEFAULT_OUTPUT_TEMPLATE

    safe_name = sanitize_filename(filename)
    name_path = Path(safe_name)
    stem = name_path.stem if name_path.suffix else name_path.name
    if not stem:
        raise ValueError("Filename must contain a base name before the extension.")
    return f"{stem}.%(ext)s"


def build_ydl_options(
    args: argparse.Namespace,
    *,
    outtmpl: str = DEFAULT_OUTPUT_TEMPLATE,
) -> tuple[Path, dict[str, object]]:
    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_options: dict[str, object] = {
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": outtmpl},
        "format": args.format,
        "format_sort": list(DEFAULT_FORMAT_SORT),
        "ignoreerrors": False,
        "noplaylist": True,
        "skip_download": args.dry_run,
        "windowsfilenames": True,
        "match_filter": build_owner_filter(args.expected_owner),
        "continuedl": True,
        "retries": 20,
        "fragment_retries": 20,
        "file_access_retries": 10,
        "extractor_retries": 5,
        "concurrent_fragment_downloads": 1,
        "external_downloader": {"m3u8": "native"},
        "merge_output_format": DEFAULT_MERGE_CONTAINER,
        "overwrites": args.overwrite,
    }

    if args.cookies:
        cookie_path = Path(args.cookies).expanduser().resolve()
        if not cookie_path.is_file():
            raise ValueError(f"Cookie file was not found: {cookie_path}")
        ydl_options["cookiefile"] = str(cookie_path)
    elif args.cookies_from_browser:
        ydl_options["cookiesfrombrowser"] = parse_browser_spec(args.cookies_from_browser)

    return output_dir, ydl_options


def build_final_output_path(
    ydl: YoutubeDL,
    info_dict: dict[str, object],
    outtmpl: str,
) -> Path:
    filename = Path(ydl.prepare_filename(info_dict, outtmpl=outtmpl))
    if info_dict.get("requested_formats"):
        return filename.with_suffix(f".{DEFAULT_MERGE_CONTAINER}")
    return filename


def build_probe_options(download_options: dict[str, object]) -> dict[str, object]:
    probe_options = deepcopy(download_options)
    probe_options["skip_download"] = True
    return probe_options


def describe_owner(info_dict: dict[str, object]) -> str:
    for field_name in OWNER_FIELDS:
        value = info_dict.get(field_name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return "unknown"


def plan_downloads(
    args: argparse.Namespace,
    download_options: dict[str, object],
) -> list[dict[str, object]]:
    planned_downloads: list[dict[str, object]] = []
    reserved_paths: set[Path] = set()

    with YoutubeDL(build_probe_options(download_options)) as probe:
        for index, url in enumerate(args.urls):
            validate_xvideos_url(url)
            info_dict = probe.extract_info(url, download=False)
            if not info_dict:
                continue

            if args.filename:
                selected_template = build_output_template(args.filename)
            else:
                preferred_path = build_final_output_path(
                    probe,
                    info_dict,
                    DEFAULT_OUTPUT_TEMPLATE,
                )
                use_collision_template = (
                    preferred_path in reserved_paths or preferred_path.exists()
                )
                selected_template = (
                    COLLISION_OUTPUT_TEMPLATE
                    if use_collision_template
                    else DEFAULT_OUTPUT_TEMPLATE
                )

            final_path = build_final_output_path(probe, info_dict, selected_template)
            reserved_paths.add(final_path)
            planned_downloads.append(
                {
                    "index": index,
                    "url": url,
                    "title": str(info_dict.get("title") or url),
                    "owner": describe_owner(info_dict),
                    "outtmpl": selected_template,
                    "path": final_path,
                }
            )

    return planned_downloads


def prompt_if_missing(args: argparse.Namespace) -> argparse.Namespace:
    if args.urls:
        return args

    if not sys.stdin.isatty():
        raise SystemExit("No URLs were provided.")

    print("Paste one or more Xvideos page URLs. Submit a blank line when finished.")
    collected: list[str] = []
    while True:
        value = input("URL: ").strip()
        if not value:
            break
        collected.append(value)

    if not collected:
        raise SystemExit("No URLs were provided.")

    args.urls = collect_urls(collected, [])

    if not args.expected_owner:
        owner = input(
            "Expected uploader/channel name (recommended, press Enter to skip): "
        ).strip()
        if owner:
            if not normalize_owner_name(owner):
                raise ValueError(
                    "Expected owner must contain at least one letter or number."
                )
            args.expected_owner = owner

    if not args.cookies and not args.cookies_from_browser:
        browser = input(
            "Browser cookies source, for example chrome or edge:Default "
            "(press Enter to skip): "
        ).strip()
        if browser:
            args.cookies_from_browser = browser

    if len(args.urls) == 1 and not args.filename:
        filename = input(
            "Optional output filename without path (press Enter to keep the site title): "
        ).strip()
        if filename:
            args.filename = filename

    return args


def print_summary(args: argparse.Namespace, output_dir: Path) -> None:
    print(f"URLs: {len(args.urls)}")
    print(f"Output directory: {output_dir}")
    print(f"Mode: {'metadata check only' if args.dry_run else 'download'}")
    print(f"Format selector: {args.format}")
    print(f"Final container: {DEFAULT_MERGE_CONTAINER}")
    if args.expected_owner:
        print(f"Expected owner: {args.expected_owner}")
    else:
        print("Expected owner: not set")
    if args.cookies_from_browser:
        print(f"Cookies from browser: {args.cookies_from_browser}")
    elif args.cookies:
        print(f"Cookies file: {Path(args.cookies).expanduser()}")
    else:
        print("Cookies: not set")
    if args.filename:
        print(f"Custom filename: {args.filename}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        args = prompt_if_missing(args)

        if args.filename and len(args.urls) > 1:
            raise ValueError("--filename can only be used when downloading one URL.")

        output_dir, ydl_options = build_ydl_options(args)
        print_summary(args, output_dir)

        planned_downloads = plan_downloads(args, ydl_options)
        if not planned_downloads:
            print("Nothing was resolved from the supplied URLs.", file=sys.stderr)
            return 1

        for plan in planned_downloads:
            print(f"Planned file: {plan['path'].name}")
            print(f"  Title: {plan['title']}")
            print(f"  Owner: {plan['owner']}")

        result = 0
        for plan in planned_downloads:
            run_options = deepcopy(ydl_options)
            run_options["outtmpl"] = {"default": str(plan["outtmpl"])}
            with YoutubeDL(run_options) as downloader:
                print(f"\nProcessing: {plan['url']}")
                result = max(result, int(downloader.download([str(plan["url"])]) or 0))
                if args.dry_run:
                    print(f"Metadata check passed for: {plan['title']}")
                else:
                    print(f"Saved to: {plan['path']}")
    except CookieLoadError:
        print(
            "Could not load cookies from the selected browser. "
            "Close the browser and try again, or use --cookies cookies.txt.",
            file=sys.stderr,
        )
        return 1
    except DownloadError as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        return 130
    except Exception as error:  # pragma: no cover - defensive fallback
        print(
            f"Unexpected error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
