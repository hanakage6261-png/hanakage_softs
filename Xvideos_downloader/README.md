# Xvideos Downloader

This script wraps `yt-dlp` so you can paste one or more Xvideos page URLs and save the video locally.

Use it only for videos that you own or have permission to download, and make sure your use follows the site's rules.

## Setup

Install or update `yt-dlp`:

```powershell
python -m pip install -U yt-dlp
```

The current script prefers H.264/AAC when available and finalizes the file as `mp4` for Windows-friendly playback.

## Quick start

Interactive mode:

```powershell
python downloader.py
```

The script will ask for:

- one or more Xvideos URLs
- an optional uploader/channel name to verify ownership
- an optional browser cookie source such as `chrome` or `edge:Default`
- an optional custom filename when downloading a single URL

Windows launcher:

Double-click [start_downloader.bat](</C:/Users/owner/Documents/花田武志/自作プログラム/01 成果物/Xvideos_downloader/start_downloader.bat>) to open the interactive prompt.

## Command line examples

Download one URL:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example"
```

Download only if the uploader metadata matches your account name:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example" --expected-owner "YourAccountName"
```

Reuse browser cookies for logged-in downloads:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example" --cookies-from-browser chrome
```

Use a specific browser profile:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example" --cookies-from-browser "edge:Default"
```

Read URLs from a text file:

```powershell
python downloader.py --url-file urls.txt --expected-owner "YourAccountName"
```

Custom filename for a single URL:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example" --filename "my_video"
```

Metadata check only:

```powershell
python downloader.py "https://www.xvideos.com/video123456/example" --expected-owner "YourAccountName" --dry-run
```

## Notes

- Only `xvideos.com` URLs are accepted.
- Files are saved into `downloads/` next to `downloader.py` by default.
- If the title-based filename would collide with an existing file, the script automatically adds the video ID for that case.
- If some URLs stop working, updating `yt-dlp` is the first thing to try.
