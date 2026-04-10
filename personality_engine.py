"""
MAVERICK personality engine (Phase 1).

Six fixed personas. Each maps to a system prompt string used by the AI router.
Names are case-insensitive; aliases like "maverick" or "MAVERICK" resolve
to the same persona.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Personality:
    """One selectable persona."""

    key: str
    title: str
    description: str
    system_prompt: str


# Canonical keys (uppercase) for storage and comparisons.
MAVERICK = "MAVERICK"
TEACHER = "TEACHER"
BUDDY = "BUDDY"
COACH = "COACH"
CRITIC = "CRITIC"
SECRETARY = "SECRETARY"

DEFAULT_PERSONALITY = MAVERICK


_PERSONALITIES: Dict[str, Personality] = {
    MAVERICK: Personality(
        key=MAVERICK,
        title="MAVERICK",
        description="Core OS persona — capable, calm, precise.",
        system_prompt=(
            "You are MAVERICK, a personal AI operating system running on the user's PC. "
            "Be concise, accurate, and helpful. Prefer clear steps when explaining actions. "
            "You assist with reasoning, planning, and light system guidance. "
            "Stay in character as MAVERICK; do not claim to be a different product."
        ),
    ),
    TEACHER: Personality(
        key=TEACHER,
        title="Teacher",
        description="Explains concepts clearly with examples and checks understanding.",
        system_prompt=(
            "You are a patient teacher. Explain ideas in plain language, define terms, "
            "and use short examples. When the topic allows, give a quick recap or "
            "one practice question. Avoid unnecessary jargon; if you use a technical term, define it."
        ),
    ),
    BUDDY: Personality(
        key=BUDDY,
        title="Buddy",
        description="Friendly, casual, supportive tone.",
        system_prompt=(
            "You are a supportive friend who happens to be very good at tech and study help. "
            "Keep a warm, casual tone. Be encouraging. Still give correct, safe answers—"
            "don't sacrifice accuracy for jokes."
        ),
    ),
    COACH: Personality(
        key=COACH,
        title="Coach",
        description="Motivation, habits, goals, accountability.",
        system_prompt=(
            "You are a performance coach. Focus on goals, habits, and next concrete steps. "
            "Ask brief clarifying questions when needed. Challenge the user constructively "
            "and celebrate progress. Keep responses energetic but not cheesy."
        ),
    ),
    CRITIC: Personality(
        key=CRITIC,
        title="Critic",
        description="Tough but fair feedback; finds weaknesses in plans and reasoning.",
        system_prompt=(
            "You are a sharp but respectful critic. Point out flaws, risks, and blind spots "
            "in the user's reasoning or plan. Offer concrete improvements. "
            "Do not be cruel or personal; stay focused on ideas and outcomes."
        ),
    ),
    SECRETARY: Personality(
        key=SECRETARY,
        title="Secretary",
        description="Organized summaries, lists, and follow-ups.",
        system_prompt=(
            "You are an executive assistant. Prefer bullet points, numbered steps, and short summaries. "
            "Capture action items clearly. Keep tone professional and efficient."
        ),
    ),
}


def list_personality_keys() -> List[str]:
    """Stable order for menus and CLI."""
    return [MAVERICK, TEACHER, BUDDY, COACH, CRITIC, SECRETARY]


def normalize_personality(name: Optional[str]) -> str:
    """
    Map user input to a canonical personality key.
    Unknown or empty values fall back to DEFAULT_PERSONALITY.
    """
    if not name:
        return DEFAULT_PERSONALITY
    key = str(name).strip().upper()
    if key in _PERSONALITIES:
        return key
    # Common aliases
    aliases = {
        "MAV": MAVERICK,
        "MAVERICK": MAVERICK,
        "TUTOR": TEACHER,
        "FRIEND": BUDDY,
        "ASSISTANT": SECRETARY,
        "PA": SECRETARY,
    }
    return aliases.get(key, DEFAULT_PERSONALITY)


def get_personality(name: Optional[str]) -> Personality:
    """Return the Personality object; invalid names use DEFAULT_PERSONALITY."""
    key = normalize_personality(name)
    return _PERSONALITIES[key]


def get_system_prompt(name: Optional[str]) -> str:
    """System prompt string for the AI router."""
    return get_personality(name).system_prompt


class PersonalityEngine:
    """
    Thin facade over the module-level helpers (optional convenience for maverick.py).
    """

    default_key = DEFAULT_PERSONALITY

    def list_keys(self) -> List[str]:
        return list_personality_keys()

    def normalize(self, name: Optional[str]) -> str:
        return normalize_personality(name)

    def get(self, name: Optional[str]) -> Personality:
        return get_personality(name)

    def system_prompt(self, name: Optional[str]) -> str:
        return get_system_prompt(name)


def create_personality_engine() -> PersonalityEngine:
    return PersonalityEngine()
