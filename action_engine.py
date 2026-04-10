"""
MAVERICK action engine (Phase 1).

Basic PC control on Windows:
- Open files, folders, URLs, or apps on PATH
- Create files (and parent directories)
- Delete files or empty directories
- Rename files or directories

Uses subprocess without shell for resolved executables; os.startfile for
files/folders/URLs (native Windows association).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import urllib.parse

from logger import MaverickLogger, create_logger


@dataclass
class ActionResult:
    ok: bool
    message: str


class ActionEngine:
    """Safe, minimal Windows-focused actions with logging to actions.log."""

    def __init__(self, logger: Optional[MaverickLogger] = None) -> None:
        self.logger = logger or create_logger()

    def _log_action(self, text: str) -> None:
        self.logger.actions(text)

    def _log_error(self, text: str) -> None:
        self.logger.error(text)

    @staticmethod
    def _resolve(path_str: str) -> Path:
        return Path(path_str).expanduser().resolve()

    def open_path(self, target: str) -> ActionResult:
        """
        Open a file, directory, or http(s) URL with the default handler.
        """
        raw = (target or "").strip()
        if not raw:
            msg = "open_path: empty target"
            self._log_error(msg)
            return ActionResult(False, msg)

        # URL
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme in ("http", "https"):
            try:
                os.startfile(raw)  # noqa: S606 - intentional Windows URL open
                self._log_action(f"Opened URL: {raw}")
                return ActionResult(True, f"Opened URL: {raw}")
            except OSError as exc:
                msg = f"open_path URL failed: {exc}"
                self._log_error(msg)
                return ActionResult(False, msg)

        path = self._resolve(raw)
        if not path.exists():
            msg = f"Path does not exist: {path}"
            self._log_error(msg)
            return ActionResult(False, msg)

        try:
            os.startfile(str(path))  # noqa: S606 - intentional Windows open
            self._log_action(f"Opened path: {path}")
            return ActionResult(True, f"Opened: {path}")
        except OSError as exc:
            msg = f"open_path failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)

    def open_app(self, name: str) -> ActionResult:
        """
        Launch an application by executable name (must be on PATH),
        e.g. notepad, calc, msedge. For full paths, use open_path instead.
        """
        raw = (name or "").strip()
        if not raw:
            msg = "open_app: empty name"
            self._log_error(msg)
            return ActionResult(False, msg)

        # If it looks like a path and exists, prefer direct open
        candidate = Path(raw).expanduser()
        if candidate.suffix.lower() in {".exe", ".bat", ".cmd", ".lnk"} and candidate.exists():
            return self.open_path(str(candidate))

        exe = shutil.which(raw)
        if not exe:
            # Try common Windows aliases
            for ext in (".exe", ".bat", ".cmd"):
                exe = shutil.which(raw + ext)
                if exe:
                    break
        if not exe:
            msg = f"Executable not found on PATH: {raw!r}"
            self._log_error(msg)
            return ActionResult(False, msg)

        try:
            # DETACHED_PROCESS avoids blocking the CLI on some GUIs
            subprocess.Popen(  # noqa: S603 - argv list, no shell
                [exe],
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._log_action(f"Launched app: {exe}")
            return ActionResult(True, f"Started: {exe}")
        except OSError as exc:
            msg = f"open_app failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)

    def create_file(self, path_str: str, content: str = "") -> ActionResult:
        """Create a file; creates parent directories if needed."""
        raw = (path_str or "").strip()
        if not raw:
            msg = "create_file: empty path"
            self._log_error(msg)
            return ActionResult(False, msg)

        path = self._resolve(raw)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._log_action(f"Created file: {path}")
            return ActionResult(True, f"Created file: {path}")
        except OSError as exc:
            msg = f"create_file failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)

    def create_dir(self, path_str: str) -> ActionResult:
        """Create a directory (and parents)."""
        raw = (path_str or "").strip()
        if not raw:
            msg = "create_dir: empty path"
            self._log_error(msg)
            return ActionResult(False, msg)

        path = self._resolve(raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
            self._log_action(f"Created directory: {path}")
            return ActionResult(True, f"Created directory: {path}")
        except OSError as exc:
            msg = f"create_dir failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)

    def delete_path(self, path_str: str) -> ActionResult:
        """
        Delete a file, or an empty directory. Refuses non-empty directories
        to avoid accidental data loss.
        """
        raw = (path_str or "").strip()
        if not raw:
            msg = "delete_path: empty path"
            self._log_error(msg)
            return ActionResult(False, msg)

        path = self._resolve(raw)
        if not path.exists():
            msg = f"Path does not exist: {path}"
            self._log_error(msg)
            return ActionResult(False, msg)

        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
                self._log_action(f"Deleted file: {path}")
                return ActionResult(True, f"Deleted file: {path}")
            if path.is_dir():
                path.rmdir()  # empty only
                self._log_action(f"Deleted empty directory: {path}")
                return ActionResult(True, f"Deleted directory: {path}")
            msg = f"Unsupported path type: {path}"
            self._log_error(msg)
            return ActionResult(False, msg)
        except OSError as exc:
            msg = f"delete_path failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)

    def rename_path(self, old_str: str, new_str: str) -> ActionResult:
        """Rename or move a file/directory within the same filesystem rules as Path.rename."""
        old_raw = (old_str or "").strip()
        new_raw = (new_str or "").strip()
        if not old_raw or not new_raw:
            msg = "rename_path: old and new paths required"
            self._log_error(msg)
            return ActionResult(False, msg)

        old = self._resolve(old_raw)
        new = Path(new_raw).expanduser()
        if not new.is_absolute():
            new = (old.parent / new).resolve()
        else:
            new = new.resolve()

        if not old.exists():
            msg = f"Source does not exist: {old}"
            self._log_error(msg)
            return ActionResult(False, msg)

        try:
            old.rename(new)
            self._log_action(f"Renamed: {old} -> {new}")
            return ActionResult(True, f"Renamed to: {new}")
        except OSError as exc:
            msg = f"rename_path failed: {exc}"
            self._log_error(msg)
            return ActionResult(False, msg)


def create_action_engine(logger: Optional[MaverickLogger] = None) -> ActionEngine:
    return ActionEngine(logger=logger)
