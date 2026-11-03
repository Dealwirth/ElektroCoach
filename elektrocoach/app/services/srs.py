"""Spaced Repetition (SM-2) und Lernplan-Logik.

Reine Rechenfunktionen ohne Seiteneffekte, damit sie testbar bleiben.
Qualitaet 0..5 wie in SM-2 ueblich (0 = total vergessen, 5 = perfekt).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
MAX_INTERVAL_DAYS = 365.0


@dataclass
class SrsState:
    ease: float = DEFAULT_EASE
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0
    state: str = "new"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ease": round(self.ease, 3),
            "interval_days": round(self.interval_days, 3),
            "repetitions": self.repetitions,
            "lapses": self.lapses,
            "state": self.state,
        }


def quality_from_score(score: float, max_points: float = 1.0) -> int:
    """Rechnet einen Bewertungs-Score in eine SM-2-Qualitaet um."""
    if max_points <= 0:
        return 0
    ratio = max(0.0, min(1.0, score / max_points))
    if ratio >= 0.98:
        return 5
    if ratio >= 0.85:
        return 4
    if ratio >= 0.7:
        return 3
    if ratio >= 0.5:
        return 2
    if ratio >= 0.25:
        return 1
    return 0


def review(state: SrsState, quality: int, now: dt.datetime | None = None) -> tuple[SrsState, dt.datetime]:
    """Fuehrt eine Wiederholung durch und liefert neuen Zustand und Faelligkeit."""
    now = now or dt.datetime.now()
    quality = max(0, min(5, int(quality)))
    new = SrsState(
        ease=state.ease, interval_days=state.interval_days,
        repetitions=state.repetitions, lapses=state.lapses, state=state.state,
    )

    if quality < 3:
        new.repetitions = 0
        new.lapses += 1
        new.interval_days = 0.5 if quality >= 1 else 0.2
        new.state = "relearning"
    else:
        new.repetitions += 1
        if new.repetitions == 1:
            new.interval_days = 1.0
        elif new.repetitions == 2:
            new.interval_days = 6.0
        else:
            new.interval_days = min(MAX_INTERVAL_DAYS, new.interval_days * new.ease)
        new.state = "review"

    new.ease = max(MIN_EASE, new.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    new.interval_days = min(MAX_INTERVAL_DAYS, max(new.interval_days, 0.2))

    due = now + dt.timedelta(days=new.interval_days)
    return new, due


def due_score(interval_days: float, days_overdue: float) -> float:
    """Prioritaet faelliger Wiederholungen: je laenger ueberfaellig, desto wichtiger."""
    return round(interval_days + max(0.0, days_overdue) * 2.0, 3)


def plan_daily_schedule(
    due_items: list[dict[str, Any]],
    minutes_available: int,
    new_item_ratio: float = 0.3,
) -> dict[str, Any]:
    """Verteilt faellige Wiederholungen und neue Fragen auf die verfuegbare Zeit.

    Die Wiederholungen werden zuerst eingeplant. Neue Fragen kommen nur in die
    verbleibende Zeit, damit das Zeitbudget nie ueberschritten wird.
    """
    seconds_per_review = 45
    seconds_per_new = 90
    budget_seconds = max(0, int(minutes_available * 60))

    due_sorted = sorted(due_items, key=lambda item: -float(item.get("priority", 0)))
    capacity_review = budget_seconds // seconds_per_review
    reviews = due_sorted[:capacity_review]

    remaining_seconds = budget_seconds - len(reviews) * seconds_per_review
    capacity_new = int(remaining_seconds * new_item_ratio / seconds_per_new)
    new_items = due_sorted[capacity_review : capacity_review + capacity_new]

    planned_minutes = round(
        (len(reviews) * seconds_per_review + len(new_items) * seconds_per_new) / 60, 1
    )
    return {
        "reviews": reviews,
        "new_items": new_items,
        "review_count": len(reviews),
        "new_count": len(new_items),
        "planned_minutes": planned_minutes,
        "capacity_review": capacity_review,
        "capacity_new": capacity_new,
    }


def mastery_level(accuracy: float, coverage: float, repetitions: int) -> dict[str, Any]:
    """Lernstand eines Themas aus Trefferquote, Abdeckung und Wiederholungen."""
    accuracy = max(0.0, min(1.0, accuracy))
    coverage = max(0.0, min(1.0, coverage))
    rep_factor = min(1.0, repetitions / 8.0)
    score = round(100 * (0.5 * accuracy + 0.3 * coverage + 0.2 * rep_factor), 1)
    if score >= 85:
        level = "sicher"
    elif score >= 65:
        level = "gefestigt"
    elif score >= 40:
        level = "uebend"
    elif score > 0:
        level = "anfangend"
    else:
        level = "offen"
    return {"score": score, "level": level}
