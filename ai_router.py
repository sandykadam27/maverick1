"""
MAVERICK AI router (Phase 1).

Priority order:
1) Groq (llama-3.3-70b-versatile)
2) Claude (optional fallback)
3) Offline-safe fallback message
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Optional, Tuple

import requests

from logger import MaverickLogger, create_logger


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_TIMEOUT = 60


@dataclass
class AIResult:
    provider: str
    text: str


def _load_env_file(env_path: str | Path = ".env") -> None:
    """Minimal .env loader without external dependency."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class AIRouter:
    """Routes prompts through Groq first, then Claude fallback."""

    def __init__(
        self,
        logger: Optional[MaverickLogger] = None,
        env_path: str | Path = ".env",
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> None:
        _load_env_file(env_path)
        self.logger = logger or create_logger()
        self.timeout_seconds = timeout_seconds
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.claude_api_key = os.getenv("CLAUDE_API_KEY", "").strip()

    def get_response(
        self,
        prompt: str,
        system_prompt: str = "You are MAVERICK, a helpful personal AI operating system.",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AIResult:
        """Get full response text with provider fallback."""
        groq_ok, groq_text = self._try_groq(prompt=prompt, system_prompt=system_prompt, history=history)
        if groq_ok:
            return AIResult(provider="groq", text=groq_text)

        claude_ok, claude_text = self._try_claude(prompt=prompt, system_prompt=system_prompt, history=history)
        if claude_ok:
            return AIResult(provider="claude", text=claude_text)

        offline = self._offline_message()
        return AIResult(provider="offline", text=offline)

    def stream_response(
        self,
        prompt: str,
        system_prompt: str = "You are MAVERICK, a helpful personal AI operating system.",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Generator[str, None, None]:
        """
        Stream response chunks.
        Falls back to non-stream call if provider stream fails.
        """
        streamed = False

        for chunk in self._stream_groq(prompt=prompt, system_prompt=system_prompt, history=history):
            streamed = True
            yield chunk
        if streamed:
            return

        for chunk in self._stream_claude(prompt=prompt, system_prompt=system_prompt, history=history):
            streamed = True
            yield chunk
        if streamed:
            return

        # Offline fallback: emit word-by-word for smooth UX.
        for token in self._offline_message().split():
            yield token + " "

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return messages

    def _try_groq(
        self,
        prompt: str,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Tuple[bool, str]:
        if not self.groq_api_key:
            self.logger.ai("Groq skipped: GROQ_API_KEY missing.")
            return False, ""

        payload = {
            "model": GROQ_MODEL,
            "messages": self._build_messages(prompt, system_prompt, history),
            "temperature": 0.5,
        }
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
            self.logger.ai("Groq response success.")
            return True, text
        except Exception as exc:  # noqa: BLE001 - keep router resilient
            self.logger.error(f"Groq request failed: {exc}")
            return False, ""

    def _try_claude(
        self,
        prompt: str,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Tuple[bool, str]:
        if not self.claude_api_key:
            self.logger.ai("Claude skipped: CLAUDE_API_KEY missing.")
            return False, ""

        # Anthropic expects user/assistant turns; system text is separate.
        messages: List[Dict[str, str]] = []
        if history:
            for item in history:
                role = item.get("role", "")
                if role in {"user", "assistant"}:
                    messages.append({"role": role, "content": item.get("content", "")})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 1200,
            "system": system_prompt,
            "messages": messages,
        }
        headers = {
            "x-api-key": self.claude_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            response = requests.post(
                CLAUDE_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            text_parts = [part.get("text", "") for part in data.get("content", []) if part.get("type") == "text"]
            text = "".join(text_parts).strip()
            if text:
                self.logger.ai("Claude response success.")
                return True, text
            return False, ""
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"Claude request failed: {exc}")
            return False, ""

    def _stream_groq(
        self,
        prompt: str,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Iterable[str]:
        if not self.groq_api_key:
            return []

        payload = {
            "model": GROQ_MODEL,
            "messages": self._build_messages(prompt, system_prompt, history),
            "temperature": 0.5,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        chunks: List[str] = []
        try:
            with requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
                stream=True,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    parsed = json.loads(data)
                    delta = parsed["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        chunks.append(delta)
                        yield delta
            if chunks:
                self.logger.ai("Groq stream success.")
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"Groq stream failed: {exc}")
            return []

    def _stream_claude(
        self,
        prompt: str,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Iterable[str]:
        if not self.claude_api_key:
            return []

        messages: List[Dict[str, str]] = []
        if history:
            for item in history:
                role = item.get("role", "")
                if role in {"user", "assistant"}:
                    messages.append({"role": role, "content": item.get("content", "")})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": CLAUDE_MODEL,
            "max_tokens": 1200,
            "system": system_prompt,
            "messages": messages,
            "stream": True,
        }
        headers = {
            "x-api-key": self.claude_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        chunks: List[str] = []
        try:
            with requests.post(
                CLAUDE_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
                stream=True,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data: "):
                        continue
                    payload_line = line[6:]
                    if payload_line == "[DONE]":
                        break
                    parsed = json.loads(payload_line)
                    if parsed.get("type") == "content_block_delta":
                        delta = parsed.get("delta", {}).get("text", "")
                        if delta:
                            chunks.append(delta)
                            yield delta
            if chunks:
                self.logger.ai("Claude stream success.")
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"Claude stream failed: {exc}")
            return []

    @staticmethod
    def _offline_message() -> str:
        return (
            "I am currently offline. Please check your internet connection "
            "or API keys, then try again."
        )
