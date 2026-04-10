"""
MAVERICK scheduler (Phase 2).

Features:
- Background daemon thread using `schedule`
- Built-in daily routines:
  - 07:00 morning
  - 21:00 study reminder
  - 22:30 night summary
- Manual trigger helpers: morning/study/night
- Custom reminders: HH:MM message
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Callable, Optional

import schedule

from logger import MaverickLogger, create_logger


SpeakFn = Callable[[str], None]
AskAIFn = Callable[[str], str]


class MaverickScheduler:
    """Schedules routines and executes them quietly in a daemon thread."""

    def __init__(
        self,
        speak_fn: SpeakFn,
        ask_ai_fn: AskAIFn,
        logger: Optional[MaverickLogger] = None,
        memory_json_path: str | Path = "memory.json",
    ) -> None:
        self.speak_fn = speak_fn
        self.ask_ai_fn = ask_ai_fn
        self.logger = logger or create_logger()
        self.memory_json_path = Path(memory_json_path).resolve()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start scheduler loop in daemon thread."""
        with self._lock:
            if self._started:
                return
            self._install_daily_jobs()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="maverick-scheduler",
                daemon=True,
            )
            self._thread.start()
            self._started = True
        self.logger.system("Scheduler started (daemon thread).")

    def stop(self, timeout_seconds: float = 2.0) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop_event.set()
            thread = self._thread
            self._started = False
        if thread:
            thread.join(timeout=timeout_seconds)
        self.logger.system("Scheduler stopped.")

    def trigger_morning(self) -> str:
        msg = self._morning_routine()
        return msg

    def trigger_study(self) -> str:
        msg = self._study_reminder()
        return msg

    def trigger_night(self) -> str:
        msg = self._night_summary()
        return msg

    def add_reminder(self, hhmm: str, message: str) -> None:
        """
        Add a daily reminder in HH:MM format (24-hour).
        """
        ts = hhmm.strip()
        text = (message or "").strip()
        if not self._valid_hhmm(ts):
            raise ValueError("Time must be HH:MM in 24-hour format.")
        if not text:
            raise ValueError("Reminder message cannot be empty.")

        def _reminder_job() -> None:
            self.speak_fn(text)
            self.logger.system(f"Reminder fired {ts}: {text}")

        schedule.every().day.at(ts).do(_reminder_job).tag(f"reminder:{ts}:{text[:24]}")
        self.logger.system(f"Reminder scheduled at {ts}: {text}")

    def _install_daily_jobs(self) -> None:
        schedule.every().day.at("07:00").do(self._morning_routine).tag("daily:morning")
        schedule.every().day.at("21:00").do(self._study_reminder).tag("daily:study")
        schedule.every().day.at("22:30").do(self._night_summary).tag("daily:night")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                schedule.run_pending()
            except Exception as exc:  # noqa: BLE001
                self.logger.error(f"Scheduler run_pending failed: {exc}")
            time.sleep(1.0)

    def _read_memory(self) -> dict:
        if not self.memory_json_path.exists():
            return {}
        try:
            return json.loads(self.memory_json_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"Failed reading memory.json: {exc}")
            return {}

    def _morning_routine(self) -> str:
        mem = self._read_memory()
        name = str(mem.get("name", "friend")).strip() or "friend"
        pending = mem.get("pending_tasks", [])
        pending_list = pending if isinstance(pending, list) else []
        tasks_text = ", ".join(str(x) for x in pending_list) if pending_list else "No pending tasks."

        prompt = (
            f"Write a short morning motivation for {name}. "
            f"Pending tasks: {tasks_text}. Keep it energetic and concise."
        )
        motivation = self._safe_ai(prompt, fallback="Let's start strong today. One step at a time.")
        text = f"Good morning {name}. Pending tasks: {tasks_text}. {motivation}"
        self.speak_fn(text)
        self.logger.system("Morning routine executed.")
        return text

    def _study_reminder(self) -> str:
        mem = self._read_memory()
        subject = str(mem.get("current_subject", "your current subject")).strip() or "your current subject"
        text = f"Study reminder: focus on {subject} now. Stay consistent."
        self.speak_fn(text)
        self.logger.system("Study reminder executed.")
        return text

    def _night_summary(self) -> str:
        prompt = (
            "Give a short night summary prompt: reflect on what was done today "
            "and add 2 practical tips to prepare for tomorrow."
        )
        summary = self._safe_ai(
            prompt,
            fallback="Review today's progress and prepare a focused top-3 plan for tomorrow.",
        )
        text = f"Night summary: {summary}"
        self.speak_fn(text)
        self.logger.system("Night summary executed.")
        return text

    def _safe_ai(self, prompt: str, fallback: str) -> str:
        try:
            out = (self.ask_ai_fn(prompt) or "").strip()
            return out if out else fallback
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"Scheduler AI callback failed: {exc}")
            return fallback

    @staticmethod
    def _valid_hhmm(value: str) -> bool:
        if len(value) != 5 or value[2] != ":":
            return False
        hh, mm = value.split(":")
        if not (hh.isdigit() and mm.isdigit()):
            return False
        h = int(hh)
        m = int(mm)
        return 0 <= h <= 23 and 0 <= m <= 59


def create_scheduler(
    speak_fn: SpeakFn,
    ask_ai_fn: AskAIFn,
    logger: Optional[MaverickLogger] = None,
    memory_json_path: str | Path = "memory.json",
) -> MaverickScheduler:
    return MaverickScheduler(
        speak_fn=speak_fn,
        ask_ai_fn=ask_ai_fn,
        logger=logger,
        memory_json_path=memory_json_path,
    )
