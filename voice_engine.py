"""
MAVERICK voice engine (Phase 2).

Non-blocking text-to-speech using edge-tts via background worker thread.
Default voices:
- Girl: en-US-AriaNeural
- Man:  en-US-GuyNeural
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Optional

from logger import MaverickLogger, create_logger


VOICE_GIRL = "en-US-AriaNeural"
VOICE_MAN = "en-US-GuyNeural"


@dataclass
class VoiceState:
    # ON by default so replies speak without an extra step; use `voice off` to disable.
    enabled: bool = True
    voice: str = VOICE_GIRL


class VoiceEngine:
    """
    Background TTS queue.

    `speak()` returns immediately, so terminal input remains responsive.
    """

    def __init__(self, logger: Optional[MaverickLogger] = None) -> None:
        self.logger = logger or create_logger()
        self.state = VoiceState()
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="maverick-voice")
        self._worker.start()

    def set_enabled(self, enabled: bool) -> None:
        self.state.enabled = enabled
        self.logger.system(f"Voice {'enabled' if enabled else 'disabled'}.")

    def set_voice_girl(self) -> None:
        self.state.voice = VOICE_GIRL
        self.logger.system(f"Voice set to {VOICE_GIRL}.")

    def set_voice_man(self) -> None:
        self.state.voice = VOICE_MAN
        self.logger.system(f"Voice set to {VOICE_MAN}.")

    def status_text(self) -> str:
        mode = "ON" if self.state.enabled else "OFF"
        return f"Voice {mode} ({self.state.voice})"

    def speak(self, text: str) -> None:
        """Queue text for speech; returns immediately."""
        if not self.state.enabled:
            return
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._queue.put(cleaned)

    def shutdown(self, timeout_seconds: float = 2.0) -> None:
        """Graceful stop for app shutdown/tests."""
        self._stop_event.set()
        self._queue.put("")  # wake worker
        self._worker.join(timeout=timeout_seconds)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if self._stop_event.is_set():
                break
            if not text:
                self._queue.task_done()
                continue
            try:
                self._speak_blocking(text=text, voice=self.state.voice)
            except Exception as exc:  # noqa: BLE001
                msg = f"Voice playback failed: {exc}"
                self.logger.error(msg)
                # Worker thread: stderr so the user sees failures even if logs are not open.
                print(msg, file=sys.stderr)
            finally:
                self._queue.task_done()

    def _speak_blocking(self, text: str, voice: str) -> None:
        """
        Generate speech with edge-tts and play it in-process via PowerShell MediaPlayer.
        This runs inside the worker thread, not on CLI input thread.
        """
        with tempfile.TemporaryDirectory(prefix="maverick_tts_") as tmp:
            media_path = Path(tmp) / f"voice_{int(time.time() * 1000)}.mp3"
            self._run_edge_tts(text=text, voice=voice, media_path=media_path)
            self._play_audio_blocking(media_path)

    def _edge_tts_command(self, text: str, voice: str, media_path: Path) -> List[str]:
        """
        Prefer `python -m edge_tts` because the `edge-tts` launcher is often not on PATH
        when edge-tts is installed with pip.
        """
        exe = shutil.which("edge-tts")
        if exe:
            return [
                exe,
                "--voice",
                voice,
                "--text",
                text,
                "--write-media",
                str(media_path),
            ]
        return [
            sys.executable,
            "-m",
            "edge_tts",
            "-v",
            voice,
            "-t",
            text,
            "--write-media",
            str(media_path),
        ]

    def _run_edge_tts(self, text: str, voice: str, media_path: Path) -> None:
        cmd = self._edge_tts_command(text=text, voice=voice, media_path=media_path)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"TTS failed ({result.returncode}): {stderr}")
        if not media_path.exists() or media_path.stat().st_size == 0:
            raise RuntimeError("TTS produced no audio file.")
        self.logger.system(f"Voice synthesized with {voice}.")

    def _play_audio_blocking(self, media_path: Path) -> None:
        """
        Play MP3 and block until playback ends.
        Prefer ffplay if present (reliable headless-style playback).
        Else use WPF MediaPlayer via PowerShell.
        """
        if not media_path.exists():
            raise FileNotFoundError(f"Missing audio file: {media_path}")

        ffplay = shutil.which("ffplay")
        if ffplay:
            r = subprocess.run(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(media_path)],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                raise RuntimeError(f"ffplay failed ({r.returncode}): {err}")
            return

        # Escape single quotes for PowerShell string literal.
        uri = media_path.resolve().as_uri().replace("'", "''")
        ps_script = (
            "$ErrorActionPreference = 'Stop'; "
            "Add-Type -AssemblyName PresentationCore; "
            "$player = New-Object System.Windows.Media.MediaPlayer; "
            f"$player.Open([uri]'{uri}'); "
            "$deadline = (Get-Date).AddSeconds(15); "
            "while($player.NaturalDuration.HasTimeSpan -eq $false){ "
            "  if((Get-Date) -gt $deadline){ throw 'Media duration not ready' }; "
            "  Start-Sleep -Milliseconds 50 "
            "}; "
            "$player.Volume = 1.0; "
            "$player.Play(); "
            "$ms = [math]::Ceiling($player.NaturalDuration.TimeSpan.TotalMilliseconds); "
            "Start-Sleep -Milliseconds $ms; "
            "$player.Stop(); "
            "$player.Close();"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"audio playback failed ({result.returncode}): {stderr}")


def create_voice_engine(logger: Optional[MaverickLogger] = None) -> VoiceEngine:
    return VoiceEngine(logger=logger)
