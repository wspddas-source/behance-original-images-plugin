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


def image_kind(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis"}:
        return "avif"
    return None


def sanitize_project_title(title: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title)
    safe = re.sub(r"\s+", " ", safe).strip(" ._")
    return safe[:80].rstrip(" ._") or "Behance项目"


def create_output_folder(desktop: Path, project_title: str) -> tuple[Path, str]:
    desktop.mkdir(parents=True, exist_ok=True)
    base = sanitize_project_title(project_title)
    number = 1
    while True:
        file_base = base if number == 1 else f"{base}_{number}"
        folder = desktop / f"{file_base}_原图"
        try:
            folder.mkdir()
            return folder, file_base
        except FileExistsError:
            number += 1


def download(
    target_name: str,
    source_name: str,
    url: str,
    folder: Path,
    opener: urllib.request.OpenerDirector,
) -> tuple[str, str]:
    target = folder / target_name
    if target.exists():
        return ("skip", target_name)

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
                if content_type == "image/gif":
                    return ("gif", target_name)
                with tempfile.NamedTemporaryFile(
                    dir=folder,
                    prefix=f".{target_name}.",
                    suffix=".part",
                    delete=False,
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    while chunk := response.read(1024 * 1024):
                        temp_file.write(chunk)
            kind = image_kind(temp_path)
            if kind == "gif":
                temp_path.unlink()
                return ("gif", target_name)
            if content_type not in IMAGE_TYPES:
                raise ValueError(f"unexpected content type: {content_type}")
            if kind is None:
                raise ValueError("downloaded content is not a recognized image")
            os.replace(temp_path, target)
            return ("ok", target_name)
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
            if temp_path and temp_path.exists():
                temp_path.unlink()
    return ("failed", f"{target_name} <- {source_name}: {last_error}")


def self_test() -> None:
    filename, url = source_url(
        "https://mir-s3-cdn-cf.behance.net/project_modules/1400_webp/demo.jpg"
    )
    assert filename == "demo.jpg"
    assert url.endswith("/project_modules/source/demo.jpg")
    assert extract_images(f'["{url}", "{url}?cache=1"]') == {
        "demo.jpg": url
    }
    assert sanitize_project_title(' My / Project: 01? ') == "My _ Project_ 01"
    with tempfile.TemporaryDirectory() as temp_dir:
        gif = Path(temp_dir) / "demo.gif"
        gif.write_bytes(b"GIF89a")
        assert image_kind(gif) == "gif"
    with tempfile.TemporaryDirectory() as temp_dir:
        desktop = Path(temp_dir)
        first, first_base = create_output_folder(desktop, "Demo")
        second, second_base = create_output_folder(desktop, "Demo")
        assert first.name == "Demo_原图" and first_base == "Demo"
        assert second.name == "Demo_2_原图" and second_base == "Demo_2"

    class FakeHeaders:
        def __init__(self, content_type: str) -> None:
            self.content_type = content_type

        def get_content_type(self) -> str:
            return self.content_type

    class FakeResponse:
        def __init__(self, content_type: str, body: bytes) -> None:
            self.headers = FakeHeaders(content_type)
            self.body = body

        def read(self, _size: int) -> bytes:
            body, self.body = self.body, b""
            return body

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeOpener:
        def __init__(self, content_type: str, body: bytes) -> None:
            self.content_type = content_type
            self.body = body

        def open(self, *_args: object, **_kwargs: object) -> FakeResponse:
            return FakeResponse(self.content_type, self.body)

    with tempfile.TemporaryDirectory() as temp_dir:
        folder = Path(temp_dir)
        assert download(
            "Demo_01.jpg",
            "source.jpg",
            "https://example.test/source.jpg",
            folder,
            FakeOpener("image/jpeg", b"\xff\xd8\xff\x00"),
        )[0] == "ok"
        assert download(
            "Demo_02.jpg",
            "source.jpg",
            "https://example.test/source.jpg",
            folder,
            FakeOpener("image/gif", b"GIF89a"),
        )[0] == "gif"
        assert download(
            "Demo_03.jpg",
            "source.jpg",
            "https://example.test/source.jpg",
            folder,
            FakeOpener("image/jpeg", b"GIF89a"),
        )[0] == "gif"
        assert sorted(path.name for path in folder.iterdir()) == ["Demo_01.jpg"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-title")
    parser.add_argument("--desktop", type=Path, default=Path.home() / "Desktop")
    parser.add_argument("--proxy", help="HTTP proxy URL; overrides system detection")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("self-test passed")
        return 0
    if not args.project_title:
        parser.error("--project-title is required")
    images = extract_images(sys.stdin.read())
    if not images:
        print("No Behance project-module image URLs found.", file=sys.stderr)
        return 1

    tasks: list[tuple[str, str, str]] = []
    gif_names: list[str] = []
    for filename, url in images.items():
        suffix = Path(filename).suffix
        if suffix.lower() == ".gif":
            gif_names.append(filename)
        else:
            tasks.append((filename, url, suffix))

    base = sanitize_project_title(args.project_title)
    if args.dry_run:
        number = 0
        for filename, url, suffix in tasks:
            number += 1
            print(f"DRY\t{base}_{number:02d}{suffix}\t{url}")
        for filename in gif_names:
            print(f"GIF_SKIPPED\t{filename}")
        return 0

    if not tasks:
        print(
            f"SUMMARY\tunique={len(images)} ok=0 skipped=0 "
            f"gif_skipped={len(gif_names)} failed=0"
        )
        return 0

    desktop = args.desktop.expanduser()
    folder, file_base = create_output_folder(desktop, args.project_title)
    targets = [
        f"{file_base}_{number:02d}{suffix}"
        for number, (_filename, _url, suffix) in enumerate(tasks, start=1)
    ]
    proxy = args.proxy or detect_system_proxy()
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        log(f"proxy={proxy}")
    else:
        opener = urllib.request.build_opener()

    counts = {"ok": 0, "skip": 0, "gif": len(gif_names), "failed": 0}
    failures: list[str] = []
    for filename in gif_names:
        log(f"GIF_SKIPPED\t{filename}")
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as executor:
        futures = [
            executor.submit(
                download,
                target_name,
                filename,
                url,
                folder,
                opener,
            )
            for target_name, (filename, url, _suffix) in zip(targets, tasks)
        ]
        for future in concurrent.futures.as_completed(futures):
            outcome, detail = future.result()
            counts[outcome] += 1
            if outcome == "failed":
                failures.append(detail)
            log(f"{outcome.upper()}\t{detail}")

    print(f"FOLDER\t{folder}")
    print(
        f"SUMMARY\tunique={len(images)} ok={counts['ok']} "
        f"skipped={counts['skip']} gif_skipped={counts['gif']} "
        f"failed={counts['failed']}"
    )
    for failure in failures:
        print(f"ERROR\t{failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
