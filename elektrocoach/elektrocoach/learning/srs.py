"""Spaced repetition scheduler (SM-2 with an Anki-style 4-point grade).

Grades: 0 = again, 1 = hard, 2 = good, 3 = easy.
The implementation follows the classic SM-2 ease/interval update, with the
well-tested Anki adjustments:

* "again" resets repetitions and shortens the interval to 10 minutes,
* "hard" multiplies the ease by 1.2 and grows the interval slowly,
* "easy" increases the ease and jumps the interval forward.

Because the interval after a lapse is expressed in fractions of a day, due
dates are stored with a time component, not just a date.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..backend.util import iso_in, iso_in_days, utcnow_iso

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
AGAIN_MINUTES = 10
LEARNING_STEPS_MINUTES = (10, 1440)  # 10 min, then 1 day


@dataclass
class ScheduleResult:
    ease: float
    interval_days: float
    repetitions: int
    lapses: int
    due_at: str
    state: str
    description: str


def review(card: dict, grade: int) -> ScheduleResult:
    """Compute the next schedule for a card. ``grade`` is 0..3."""

    grade = max(0, min(3, int(grade)))
    ease = float(card.get("ease") or DEFAULT_EASE)
    interval = float(card.get("interval_days") or 0.0)
    repetitions = int(card.get("repetitions") or 0)
    lapses = int(card.get("lapses") or 0)
    state = str(card.get("state") or "new")

    if grade == 0:  # again
        lapses += 1
        ease = max(MIN_EASE, ease - 0.2)
        repetitions = 0
        interval = AGAIN_MINUTES / 1440.0
        state = "learning"
        due = iso_in(AGAIN_MINUTES * 60)
        return ScheduleResult(ease, interval, repetitions, lapses, due, state,
                              "Die Karte wird in 10 Minuten erneut gezeigt.")

    # A brand new or relearning card moves through the learning steps first.
    if state in {"new", "learning"} and repetitions == 0:
        if grade == 1:
            interval = LEARNING_STEPS_MINUTES[0] / 1440.0
            due = iso_in(LEARNING_STEPS_MINUTES[0] * 60)
            description = "Die Karte wird in 10 Minuten erneut gezeigt."
        elif grade == 2:
            interval = LEARNING_STEPS_MINUTES[1] / 1440.0
            due = iso_in_days(1)
            description = "Die Karte wird morgen erneut gezeigt."
        else:  # easy: skip the remaining learning steps
            interval = 4.0
            ease = min(3.2, ease + 0.15)
            due = iso_in_days(4)
            description = "Die Karte wird in 4 Tagen erneut gezeigt."
        return ScheduleResult(ease, interval, repetitions + 1, lapses, due,
                              "learning", description)

    # Review card.
    if grade == 1:
        ease = max(MIN_EASE, ease - 0.15)
        interval = max(1.0, interval * 1.2)
        description = f"Die Karte wird in {interval:.0f} Tag(en) erneut gezeigt."
    elif grade == 2:
        if interval < 1:
            interval = 1.0
        else:
            interval = max(1.0, interval * ease)
        description = f"Die Karte wird in {interval:.0f} Tag(en) erneut gezeigt."
    else:  # easy
        ease = min(3.2, ease + 0.15)
        if interval < 1:
            interval = 4.0
        else:
            interval = max(1.0, interval * ease * 1.3)
        description = f"Die Karte wird in {interval:.0f} Tag(en) erneut gezeigt."

    # Cap the interval so the SD-card database never holds absurd dates.
    interval = min(interval, 365.0)
    return ScheduleResult(ease, round(interval, 4), repetitions + 1, lapses,
                          iso_in_days(interval), "review", description)


def apply_attempt_grade(card: dict, *, correct: bool, score_ratio: float,
                        duration_ms: int | None = None) -> ScheduleResult:
    """Derive a 0..3 grade from a graded answer and reschedule."""

    if not correct and score_ratio < 0.3:
        grade = 0
    elif score_ratio >= 0.95:
        grade = 3
    elif score_ratio >= 0.6:
        grade = 2
    else:
        grade = 1
    if correct and duration_ms is not None and duration_ms > 120_000 and grade > 1:
        # A very slow but correct answer is treated as "hard".
        grade = 1
    return review(card, grade)


def retention_forecast(cards: list[dict], days: int = 14) -> list[dict]:
    """Group upcoming due dates per day for the study plan view."""

    buckets: dict[str, int] = {}
    now = utcnow_iso()[:10]
    for card in cards:
        due = str(card.get("due_at") or "")[:10]
        if not due:
            continue
        buckets[due] = buckets.get(due, 0) + 1
    return [{"day": day, "count": count} for day, count in sorted(buckets.items())
            if day >= now][:days]
