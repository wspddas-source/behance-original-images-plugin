#!/usr/bin/env python3
"""Download original images from rendered Behance project-module URLs."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


URL_RE = re.compile(
    r"https://mir-s3-cdn-cf\.behance\.net/project_modules/[^\s\"'<>\\]+"
)
IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}
print_lock = threading.Lock()


def log(message: str) -> None:
    with print_lock:
        print(message, flush=True)


def source_url(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url)
    if parts.hostname != "mir-s3-cdn-cf.behance.net":
        raise ValueError(f"unexpected image host: {parts.hostname}")
    segments = [segment for segment in parts.path.split("/") if segment]
    if "project_modules" not in segments:
        raise ValueError(f"not a project-module URL: {url}")
    index = segments.index("project_modules")
    if index + 2 >= len(segments):
        raise ValueError(f"missing image filename: {url}")
    filename = urllib.parse.unquote(segments[-1])
    if Path(filename).name != filename:
        raise ValueError(f"unsafe image filename: {filename}")
    original = urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            f"/project_modules/source/{urllib.parse.quote(filename)}",
            "",
            "",
        )
    )
    return filename, original


def extract_images(text: str) -> dict[str, str]:
    images: dict[str, str] = {}
    for match in URL_RE.findall(text):
        filename, original = source_url(match.rstrip(".,;)"))
        images.setdefault(filename, original)
    return images


def detect_system_proxy() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        text = subprocess.run(
            ["scutil", "--proxy"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    def value(key: str) -> str | None:
        found = re.search(rf"^\s*{key}\s*:\s*(\S+)\s*$", text, re.MULTILINE)
        return found.group(1) if found else None

    if value("HTTPSEnable") == "1":
        host = value("HTTPSProxy")
        port = value("HTTPSPort")
    elif value("HTTPEnable") == "1":
        host = value("HTTPProxy")
        port = value("HTTPPort")
    else:
        return None
    if host and port:
        return f"http://{host}:{port}"
    return None


def looks_like_image(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    return (
        head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith((b"GIF87a", b"GIF89a"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
        or (head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis"})
    )


def download(
    filename: str,
    url: str,
    destination: Path,
    opener: urllib.request.OpenerDirector,
) -> tuple[str, str]:
    target = destination / filename
    if target.exists():
        if looks_like_image(target):
            return ("skip", filename)
        return ("failed", f"{filename}: existing file is not a recognized image")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
        },
    )
    last_error: Exception | None = None
    for _attempt in range(3):
        temp_path: Path | None = None
        try:
            with opener.open(request, timeout=90) as response:
                content_type = response.headers.get_content_type()
                if content_type not in IMAGE_TYPES:
                    raise ValueError(f"unexpected content type: {content_type}")
                with tempfile.NamedTemporaryFile(
                    dir=destination,
                    prefix=f".{filename}.",
                    suffix=".part",
                    delete=False,
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    while chunk := response.read(1024 * 1024):
                        temp_file.write(chunk)
            if not looks_like_image(temp_path):
                raise ValueError("downloaded content is not a recognized image")
            os.replace(temp_path, target)
            return ("ok", filename)
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
            if temp_path and temp_path.exists():
                temp_path.unlink()
    return ("failed", f"{filename}: {last_error}")


def self_test() -> None:
    filename, url = source_url(
        "https://mir-s3-cdn-cf.behance.net/project_modules/1400_webp/demo.jpg"
    )
    assert filename == "demo.jpg"
    assert url.endswith("/project_modules/source/demo.jpg")
    assert extract_images(f'["{url}", "{url}?cache=1"]') == {
        "demo.jpg": url
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", help="Output directory")
    parser.add_argument("--proxy", help="HTTP proxy URL; overrides system detection")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("self-test passed")
        return 0
    if not args.destination:
        parser.error("destination is required")

    images = extract_images(sys.stdin.read())
    if not images:
        print("No Behance project-module image URLs found.", file=sys.stderr)
        return 1
    if args.dry_run:
        for filename, url in images.items():
            print(f"DRY\t{filename}\t{url}")
        return 0

    destination = Path(args.destination).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    proxy = args.proxy or detect_system_proxy()
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        log(f"proxy={proxy}")
    else:
        opener = urllib.request.build_opener()

    counts = {"ok": 0, "skip": 0, "failed": 0}
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as executor:
        futures = [
            executor.submit(download, filename, url, destination, opener)
            for filename, url in images.items()
        ]
        for future in concurrent.futures.as_completed(futures):
            outcome, detail = future.result()
            counts[outcome] += 1
            if outcome == "failed":
                failures.append(detail)
            log(f"{outcome.upper()}\t{detail}")

    print(
        f"SUMMARY\tunique={len(images)} ok={counts['ok']} "
        f"skipped={counts['skip']} failed={counts['failed']}"
    )
    for failure in failures:
        print(f"ERROR\t{failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
