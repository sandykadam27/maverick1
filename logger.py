"""
MAVERICK logger module (Phase 1).

Creates and manages six dedicated log files:
- system.log
- ai.log
- memory.log
- actions.log
- errors.log
- security.log
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
from logging import Logger
from logging.handlers import RotatingFileHandler
from typing import Dict


LOG_NAMES = ("system", "ai", "memory", "actions", "errors", "security")


@dataclass(frozen=True)
class LoggerPaths:
    """Container for resolved log directory and files."""

    base_dir: Path
    files: Dict[str, Path]


class MaverickLogger:
    """
    Central logging manager for MAVERICK.

    Usage:
        logs = MaverickLogger()
        logs.system("Boot sequence complete.")
        logs.ai("Sending prompt to provider.")
        logs.error("Provider request failed.")
    """

    def __init__(
        self,
        log_dir: str | Path = "logs",
        max_bytes: int = 1_000_000,
        backup_count: int = 3,
    ) -> None:
        self.paths = self._build_paths(log_dir)
        self._loggers = self._build_loggers(max_bytes=max_bytes, backup_count=backup_count)

    @staticmethod
    def _build_paths(log_dir: str | Path) -> LoggerPaths:
        base_dir = Path(log_dir).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        files = {name: base_dir / f"{name}.log" for name in LOG_NAMES}
        return LoggerPaths(base_dir=base_dir, files=files)

    def _build_loggers(self, max_bytes: int, backup_count: int) -> Dict[str, Logger]:
        logger_map: Dict[str, Logger] = {}

        for name, file_path in self.paths.files.items():
            logger = logging.getLogger(f"maverick.{name}")
            logger.setLevel(logging.INFO)
            logger.propagate = False

            # Avoid duplicate handlers when module is reloaded.
            if logger.handlers:
                logger.handlers.clear()

            handler = RotatingFileHandler(
                filename=file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger_map[name] = logger

        return logger_map

    def get_logger(self, name: str) -> Logger:
        """Return a named logger. Raises ValueError if unknown."""
        if name not in self._loggers:
            valid = ", ".join(LOG_NAMES)
            raise ValueError(f"Unknown log channel '{name}'. Valid channels: {valid}")
        return self._loggers[name]

    def system(self, message: str) -> None:
        self._loggers["system"].info(message)

    def ai(self, message: str) -> None:
        self._loggers["ai"].info(message)

    def memory(self, message: str) -> None:
        self._loggers["memory"].info(message)

    def actions(self, message: str) -> None:
        self._loggers["actions"].info(message)

    def error(self, message: str) -> None:
        self._loggers["errors"].error(message)

    def security(self, message: str) -> None:
        self._loggers["security"].warning(message)


def create_logger(log_dir: str | Path = "logs") -> MaverickLogger:
    """Convenience factory for app startup."""
    return MaverickLogger(log_dir=log_dir)
