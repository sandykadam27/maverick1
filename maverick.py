"""
MAVERICK — Phase 1 main entry.

Rich terminal UI, Groq → Claude → offline routing, six personalities,
SQLite memory, Windows actions, logging, rate limiting, streamed replies.
"""

from __future__ import annotations

import shlex
import sys
import threading
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from action_engine import create_action_engine
from ai_router import AIRouter
from downloader import create_downloader
from logger import create_logger
from pattern_engine import create_pattern_engine
from personality_engine import (
    DEFAULT_PERSONALITY,
    get_system_prompt,
    list_personality_keys,
    normalize_personality,
)
from rate_limiter import create_rate_limiter
from scheduler import create_scheduler
from storage import create_storage
from voice_engine import create_voice_engine


# Must match ai_router.AIRouter._offline_message() text for status labeling.
_OFFLINE_REPLY = (
    "I am currently offline. Please check your internet connection "
    "or API keys, then try again."
)


THEME = Theme(
    {
        "maverick": "bold cyan",
        "dim": "dim",
        "ok": "green",
        "warn": "yellow",
        "err": "red",
        "provider": "magenta",
    }
)


class MaverickApp:
    """Wires MAVERICK modules into a single interactive session."""

    def __init__(self) -> None:
        self.console = Console(theme=THEME)
        self.logger = create_logger()
        self.storage = create_storage(logger=self.logger)
        self.router = AIRouter(logger=self.logger)
        self.limiter = create_rate_limiter(logger=self.logger)
        self.actions = create_action_engine(logger=self.logger)
        self.voice = create_voice_engine(logger=self.logger)
        self.downloader = create_downloader(logger=self.logger)
        self.patterns = create_pattern_engine(logger=self.logger)

        self.personality: str = DEFAULT_PERSONALITY
        self.session_id: str = self.storage.new_session(self.personality, title="CLI session")
        self.scheduler = create_scheduler(
            speak_fn=self._scheduler_speak,
            ask_ai_fn=self._scheduler_ask_ai,
            logger=self.logger,
            memory_json_path="memory.json",
        )

    def banner(self) -> None:
        self.console.print(
            Panel.fit(
                "[bold cyan]MAVERICK[/] — Personal AI OS (Phase 1)\n"
                "[dim]Type [bold]help[/] for commands. [bold]exit[/] to quit.[/]",
                border_style="cyan",
            )
        )

    def handle_builtin(self, line: str) -> bool:
        """
        Process slash-style and keyword commands. Returns True if the line
        was fully handled (no AI call). False means treat as chat input.
        """
        raw = line.strip()
        if not raw:
            return True

        # Slash aliases: /help -> help
        if raw.startswith("/"):
            raw = raw[1:].strip()
            if not raw:
                return True

        low = raw.lower()
        parts = raw.split()
        head = parts[0].lower()

        if low in ("exit", "quit", "bye"):
            self.console.print("[dim]Goodbye.[/]")
            sys.exit(0)

        if head in ("help", "?", "h"):
            self._print_help()
            return True

        if head == "status":
            self._print_status()
            return True
        if head == "voice":
            return self._cmd_voice(parts)
        if head == "trigger":
            return self._cmd_trigger(parts)
        if head == "remind":
            return self._cmd_remind(raw)
        if low == "my downloads":
            return self._cmd_my_downloads()
        if low == "my patterns":
            return self._cmd_my_patterns()
        if head == "download":
            return self._cmd_download(raw)

        if head in ("personality", "person", "p"):
            return self._cmd_personality(parts)

        if head == "new" and len(parts) > 1 and parts[1].lower() == "session":
            self._new_session()
            return True
        if low == "new" or low == "new session":
            self._new_session()
            return True

        if head == "open":
            return self._cmd_open(raw)

        if head == "create":
            return self._cmd_create(raw)

        if head in ("delete", "rm"):
            return self._cmd_delete(raw)

        if head in ("rename", "mv"):
            return self._cmd_rename(raw)

        return False

    def _print_status(self) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("Personality", f"[maverick]{self.personality}[/]")
        table.add_row("Session", f"[dim]{self.session_id[:8]}…[/]")
        table.add_row("API budget", f"{self.limiter.remaining()} / min (approx)")
        table.add_row("Voice", self.voice.status_text())
        self.console.print(Panel(table, title="Status", border_style="cyan"))

    def _print_help(self) -> None:
        table = Table(title="Commands", show_lines=True)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")
        rows = [
            ("help", "Show this help."),
            ("status", "Personality, session, rate limit headroom."),
            ("personality list", "List personas."),
            ("personality set <name>", "Switch persona (starts new session)."),
            ("new session", "Start a fresh chat session."),
            ("voice on|off", "Enable or disable voice output."),
            ("voice girl|man", "Switch voice to Aria or Guy."),
            ("trigger morning|study|night", "Run a routine immediately."),
            ("remind HH:MM <message>", "Add a daily reminder."),
            ("download <url>", "Download direct URL to MAVERICK downloads."),
            ("download apk <url>", "Download URL and force .apk extension."),
            ("my downloads", "Show recent downloaded files."),
            ("my patterns", "Show learned activity patterns."),
            ("open <path|url>", "Open file, folder, or http(s) URL."),
            ("open app <name>", "Launch an app on PATH (e.g. notepad)."),
            ("create file <path> [text…]", "Create a UTF-8 text file."),
            ("create dir <path>", "Create a directory."),
            ("delete <path>", "Delete a file or empty folder."),
            ("rename <old> <new>", "Rename/move (quote paths with spaces)."),
            ("exit", "Quit MAVERICK."),
        ]
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        self.console.print(table)
        self.console.print(
            "[dim]Chat anything else goes to the AI (streamed). "
            "Keys: set GROQ_API_KEY / CLAUDE_API_KEY in .env[/]"
        )

    def _cmd_personality(self, parts: List[str]) -> bool:
        if len(parts) == 1:
            self.console.print(
                f"[warn]Usage:[/] personality list | personality set <name> | personality current"
            )
            return True
        sub = parts[1].lower()
        if sub == "list":
            keys = list_personality_keys()
            self.console.print("[bold]Personalities:[/] " + ", ".join(keys))
            return True
        if sub == "current":
            self.console.print(f"[maverick]{self.personality}[/]")
            return True
        if sub == "set" and len(parts) >= 3:
            name = " ".join(parts[2:])
            self.personality = normalize_personality(name)
            self.console.print(f"[ok]Personality → {self.personality}[/]")
            self._new_session()
            return True
        self.console.print("[err]Usage:[/] personality set TEACHER (etc.)")
        return True

    def _cmd_voice(self, parts: List[str]) -> bool:
        if len(parts) < 2:
            self.console.print("[warn]Usage:[/] voice on|off|girl|man")
            return True
        sub = parts[1].lower()
        if sub == "on":
            self.voice.set_enabled(True)
            self.console.print("[ok]Voice enabled.[/]")
            return True
        if sub == "off":
            self.voice.set_enabled(False)
            self.console.print("[ok]Voice disabled.[/]")
            return True
        if sub == "girl":
            self.voice.set_voice_girl()
            self.console.print("[ok]Voice set to girl (Aria).[/]")
            return True
        if sub == "man":
            self.voice.set_voice_man()
            self.console.print("[ok]Voice set to man (Guy).[/]")
            return True
        self.console.print("[warn]Usage:[/] voice on|off|girl|man")
        return True

    def _cmd_trigger(self, parts: List[str]) -> bool:
        if len(parts) < 2:
            self.console.print("[warn]Usage:[/] trigger morning|study|night")
            return True
        sub = parts[1].lower()
        if sub == "morning":
            msg = self.scheduler.trigger_morning()
        elif sub == "study":
            msg = self.scheduler.trigger_study()
        elif sub == "night":
            msg = self.scheduler.trigger_night()
        else:
            self.console.print("[warn]Usage:[/] trigger morning|study|night")
            return True
        self.console.print(f"[ok]{msg}[/]")
        return True

    def _cmd_remind(self, raw: str) -> bool:
        tokens = raw.split(maxsplit=2)
        if len(tokens) < 3:
            self.console.print("[warn]Usage:[/] remind HH:MM <message>")
            return True
        _, hhmm, msg = tokens
        try:
            self.scheduler.add_reminder(hhmm, msg)
            self.console.print(f"[ok]Daily reminder set for {hhmm}.[/]")
        except ValueError as exc:
            self.console.print(f"[err]{exc}[/]")
        return True

    def _cmd_download(self, raw: str) -> bool:
        try:
            tokens = shlex.split(raw, posix=False)
        except ValueError as exc:
            self.console.print(f"[err]{exc}[/]")
            return True
        if len(tokens) < 2:
            self.console.print("[warn]Usage:[/] download <url> | download apk <url>")
            return True
        is_apk = len(tokens) >= 3 and tokens[1].lower() == "apk"
        url = tokens[2] if is_apk else tokens[1]
        self.console.print("[dim]Downloading...[/]")
        progress_lock = threading.Lock()
        last_print = {"v": -1}

        def on_progress(percent: int) -> None:
            with progress_lock:
                # Reduce noisy output: every 10% plus completion.
                if percent == 100 or percent // 10 > last_print["v"] // 10:
                    last_print["v"] = percent
                    self.console.print(f"[dim]{percent}%[/]")

        if is_apk:
            res = self.downloader.download_apk(url, progress_callback=on_progress)
        else:
            res = self.downloader.download(url, progress_callback=on_progress)
        self._print_action_result(res)
        return True

    def _cmd_my_downloads(self) -> bool:
        files = self.downloader.list_downloads(limit=20)
        if not files:
            self.console.print("[dim]No downloads yet.[/]")
            return True
        table = Table(title="My Downloads", show_lines=False)
        table.add_column("File", style="cyan")
        table.add_column("Size")
        for p in files:
            size = p.stat().st_size
            table.add_row(p.name, f"{size} bytes")
        self.console.print(table)
        return True

    def _cmd_my_patterns(self) -> bool:
        report = self.patterns.patterns_report()
        self.console.print(Panel(report, title="My Patterns", border_style="cyan"))
        return True

    def _new_session(self) -> None:
        self.session_id = self.storage.new_session(self.personality, title="CLI session")
        self.console.print(f"[dim]New session {self.session_id[:8]}…[/]")

    def _cmd_open(self, raw: str) -> bool:
        if len(raw) < 4 or raw[:4].lower() != "open":
            self.console.print("[warn]Usage:[/] open <path|url>  |  open app <name>")
            return True
        rest = raw[4:].strip()  # after "open"
        if not rest:
            self.console.print("[warn]Usage:[/] open <path|url>  |  open app <name>")
            return True
        if rest.lower().startswith("app "):
            target = rest[4:].strip()
            if not target:
                self.console.print("[warn]Usage:[/] open app notepad")
                return True
            res = self.actions.open_app(target)
            self._print_action_result(res)
            return True
        res = self.actions.open_path(rest)
        self._print_action_result(res)
        return True

    def _cmd_create(self, raw: str) -> bool:
        try:
            tokens = shlex.split(raw, posix=False)
        except ValueError as exc:
            self.console.print(f"[err]{exc}[/]")
            return True
        if len(tokens) < 2:
            self.console.print("[warn]Usage:[/] create file <path> [content…]  |  create dir <path>")
            return True
        kind = tokens[1].lower()
        if kind == "file":
            if len(tokens) < 3:
                self.console.print("[warn]Usage:[/] create file <path> [content…]")
                return True
            path = tokens[2]
            content = " ".join(tokens[3:]) if len(tokens) > 3 else ""
            res = self.actions.create_file(path, content)
            self._print_action_result(res)
            return True
        if kind in ("dir", "folder"):
            if len(tokens) < 3:
                self.console.print("[warn]Usage:[/] create dir <path>")
                return True
            res = self.actions.create_dir(tokens[2])
            self._print_action_result(res)
            return True
        self.console.print("[warn]Expected[/] create file … [dim]or[/] create dir …")
        return True

    def _cmd_delete(self, raw: str) -> bool:
        try:
            tokens = shlex.split(raw, posix=False)
        except ValueError as exc:
            self.console.print(f"[err]{exc}[/]")
            return True
        if len(tokens) < 2:
            self.console.print("[warn]Usage:[/] delete <path>")
            return True
        path = tokens[1]
        res = self.actions.delete_path(path)
        self._print_action_result(res)
        return True

    def _cmd_rename(self, raw: str) -> bool:
        try:
            tokens = shlex.split(raw, posix=False)
        except ValueError as exc:
            self.console.print(f"[err]{exc}[/]")
            return True
        if len(tokens) < 3:
            self.console.print("[warn]Usage:[/] rename <old> <new>")
            return True
        old, new = tokens[1], tokens[2]
        res = self.actions.rename_path(old, new)
        self._print_action_result(res)
        return True

    def _print_action_result(self, res) -> None:
        if res.ok:
            self.console.print(f"[ok]{res.message}[/]")
        else:
            self.console.print(f"[err]{res.message}[/]")

    def _chat_turn(self, user_text: str) -> None:
        """Stream AI reply, persist messages, show provider."""
        system_prompt = get_system_prompt(self.personality)
        history = self.storage.get_history_for_api(self.session_id, limit=40)

        if not self.limiter.allow():
            self.console.print(
                "[warn]Rate limit: too many requests this minute. Try again shortly.[/]"
            )
            return

        self.console.print()
        collected: List[str] = []

        try:
            for chunk in self.router.stream_response(
                prompt=user_text,
                system_prompt=system_prompt,
                history=history,
            ):
                collected.append(chunk)
                self.console.print(chunk, end="", highlight=False)
        except KeyboardInterrupt:
            self.console.print("\n[dim]Interrupted.[/]")
            return

        reply = "".join(collected).strip()
        self.console.print()

        if reply.strip() == _OFFLINE_REPLY.strip():
            tag = "offline"
        else:
            tag = "ai"
        self.console.print(f"[dim][{tag}][/]\n")
        self.voice.speak(reply)

        # Persist after successful generation (user was not stored yet).
        try:
            self.storage.append_message(self.session_id, "user", user_text, self.personality)
            self.storage.append_message(
                self.session_id, "assistant", reply or "(empty)", self.personality
            )
        except Exception as exc:  # noqa: BLE001 - persist failures should not crash CLI
            self.logger.error(f"Failed to save messages: {exc}")
            self.console.print(f"[err]Could not save conversation: {exc}[/]")

        # Optional: render final assistant text as Markdown for nicer display — Phase 1 keeps stream plain.

    def run(self) -> None:
        self.logger.system("MAVERICK CLI starting.")
        self.scheduler.start()
        self.banner()

        try:
            while True:
                try:
                    line = self.console.input("[bold cyan]MAVERICK[/] › ").rstrip("\n")
                except (EOFError, KeyboardInterrupt):
                    self.console.print("\n[dim]Goodbye.[/]")
                    break

                if not line.strip():
                    continue

                self.patterns.record_command(line)
                if self.handle_builtin(line):
                    continue

                self._chat_turn(line)
        finally:
            self.scheduler.stop()
            self.voice.shutdown()

    def _scheduler_speak(self, text: str) -> None:
        """Called from scheduler thread: keep silent in terminal, speak if enabled."""
        self.logger.system(f"Routine: {text}")
        self.voice.speak(text)

    def _scheduler_ask_ai(self, prompt: str) -> str:
        """
        Scheduler AI callback uses non-stream text response.
        Falls back naturally through router.
        """
        if not self.limiter.allow():
            return "Let's keep momentum and continue with your plan."
        result = self.router.get_response(
            prompt=prompt,
            system_prompt=get_system_prompt(self.personality),
            history=None,
        )
        return result.text


def main(argv: Optional[List[str]] = None) -> None:
    _ = argv
    app = MaverickApp()
    app.run()


if __name__ == "__main__":
    main(sys.argv[1:])
