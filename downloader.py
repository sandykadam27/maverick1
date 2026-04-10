"""
MAVERICK downloader (Phase 2).

- Download files from direct URLs using requests
- Save under: C:\\Users\\workk\\Downloads\\MAVERICK\\
- Progress callback support (percentage updates)
- Helper for APK downloads
- List downloaded files
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, unquote

import requests

from logger import MaverickLogger, create_logger


DEFAULT_DOWNLOAD_DIR = Path(r"C:\Users\workk\Downloads\MAVERICK")
ProgressFn = Callable[[int], None]


@dataclass
class DownloadResult:
    ok: bool
    message: str
    path: Optional[Path] = None
    bytes_downloaded: int = 0


class AutoDownloader:
    """Simple file downloader with progress reporting."""

    def __init__(
        self,
        download_dir: Path | str = DEFAULT_DOWNLOAD_DIR,
        logger: Optional[MaverickLogger] = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.download_dir = Path(download_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or create_logger()
        self.timeout_seconds = timeout_seconds

    def download(
        self,
        url: str,
        force_extension: Optional[str] = None,
        progress_callback: Optional[ProgressFn] = None,
    ) -> DownloadResult:
        raw = (url or "").strip()
        if not raw:
            return DownloadResult(False, "URL is required.")
        if not (raw.startswith("http://") or raw.startswith("https://")):
            return DownloadResult(False, "Only http(s) URLs are supported.")

        try:
            with requests.get(raw, stream=True, timeout=self.timeout_seconds) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", "0") or "0")
                filename = self._resolve_filename(raw, resp.headers.get("content-disposition"), force_extension)
                out_path = self.download_dir / filename
                out_path = self._avoid_collision(out_path)

                downloaded = 0
                last_percent = -1
                with out_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = self._compute_percent(downloaded, total)
                        if percent != last_percent:
                            last_percent = percent
                            if progress_callback:
                                progress_callback(percent)

                self.logger.actions(f"Downloaded: {raw} -> {out_path}")
                return DownloadResult(
                    ok=True,
                    message=f"Downloaded to {out_path}",
                    path=out_path,
                    bytes_downloaded=downloaded,
                )
        except requests.RequestException as exc:
            msg = f"Download failed: {exc}"
            self.logger.error(msg)
            return DownloadResult(False, msg)
        except OSError as exc:
            msg = f"File write failed: {exc}"
            self.logger.error(msg)
            return DownloadResult(False, msg)

    def download_apk(self, url: str, progress_callback: Optional[ProgressFn] = None) -> DownloadResult:
        return self.download(url=url, force_extension=".apk", progress_callback=progress_callback)

    def list_downloads(self, limit: int = 50) -> list[Path]:
        if not self.download_dir.exists():
            return []
        files = [p for p in self.download_dir.iterdir() if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[: max(0, limit)]

    @staticmethod
    def _compute_percent(downloaded: int, total: int) -> int:
        if total <= 0:
            return 0
        pct = int((downloaded / total) * 100)
        return max(0, min(100, pct))

    def _resolve_filename(
        self,
        url: str,
        content_disposition: Optional[str],
        force_extension: Optional[str],
    ) -> str:
        # Try Content-Disposition first.
        cd_name = self._filename_from_content_disposition(content_disposition)
        if cd_name:
            base = cd_name
        else:
            parsed = urlparse(url)
            base = unquote(Path(parsed.path).name) or f"download_{datetime.now():%Y%m%d_%H%M%S}"

        base = base.strip().replace("\n", "_").replace("\r", "_")
        if force_extension:
            ext = force_extension if force_extension.startswith(".") else f".{force_extension}"
            if not base.lower().endswith(ext.lower()):
                stem = Path(base).stem or "download"
                base = f"{stem}{ext}"
        return base

    @staticmethod
    def _filename_from_content_disposition(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        marker = "filename="
        lower = value.lower()
        idx = lower.find(marker)
        if idx == -1:
            return None
        name = value[idx + len(marker) :].strip().strip('"').strip("'")
        return name or None

    @staticmethod
    def _avoid_collision(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        for i in range(1, 10_000):
            candidate = parent / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                return candidate
        raise OSError("Unable to create unique filename.")


def create_downloader(
    download_dir: Path | str = DEFAULT_DOWNLOAD_DIR,
    logger: Optional[MaverickLogger] = None,
    timeout_seconds: int = 120,
) -> AutoDownloader:
    return AutoDownloader(download_dir=download_dir, logger=logger, timeout_seconds=timeout_seconds)
