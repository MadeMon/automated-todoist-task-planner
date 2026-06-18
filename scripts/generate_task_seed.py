#!/usr/bin/env python3
"""Generate task seed JSON for scheduler testing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from typing import Any


PROJECT_NAME = "PA026 Playground"
FIXED_TASK_CONTENT = "Fixed"
FLEX_CONTENT_WITH_DEADLINE_TEMPLATE = "{duration}min | D {days}d"
FLEX_CONTENT_NO_DEADLINE_TEMPLATE = "{duration} min"

FIXED_TASK_LABELS = ["fixed"]
FLEX_TASK_LABELS: list[str] = []

JSON_INDENT = 2
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR
TIME_FIELD_WIDTH = 2

DURATION_MIN_MINUTES = 5
DURATION_MAX_MINUTES = 180
FIXED_DURATION_MAX_MINUTES = 60
SHORT_DURATION_THRESHOLD_MINUTES = 60
SHORT_DURATION_WEIGHT = 2.0
LONG_DURATION_WEIGHT_START = 1.0
LONG_DURATION_WEIGHT_END = 0.2
PRIORITY_MIN = 1
PRIORITY_MAX = 4
FIXED_PRIORITY = 1
DEADLINE_OFFSET_MIN_DAYS = 0
DEADLINE_OFFSET_MAX_DAYS = 14
NO_DEADLINE_PROBABILITY = 0.05

DUE_OFFSET_DAYS = 0
DUE_START_HOUR = 10
DUE_START_MINUTE = 0

FIXED_WINDOW_START_OFFSET_DAYS = 0
FIXED_WINDOW_DAYS = 14
FIXED_WINDOW_START_HOUR = 9
FIXED_WINDOW_START_MINUTE = 0
FIXED_WINDOW_END_HOUR = 17
FIXED_WINDOW_END_MINUTE = 0
FIXED_MIN_GAP_MINUTES = 30

# Gap distribution configuration
GAP_MAIN_RANGE_MIN_MINUTES = 30
GAP_MAIN_RANGE_MAX_MINUTES = 180
GAP_MAIN_RANGE_PROBABILITY = 0.8  # 80% probability for main range
GAP_ALT_RANGE_MIN_MINUTES = 10
GAP_ALT_RANGE_MAX_MINUTES = 30  # Alternative range for remaining 20%

COPIES_DEFAULT = 1
RNG_SEED = None

DURATION_WEIGHT_DECAY_SPAN_MINUTES = (
    DURATION_MAX_MINUTES - SHORT_DURATION_THRESHOLD_MINUTES
)
DURATION_WEIGHT_DECAY_PER_MINUTE = (
    (LONG_DURATION_WEIGHT_START - LONG_DURATION_WEIGHT_END)
    / DURATION_WEIGHT_DECAY_SPAN_MINUTES
)


def _time_to_minutes(hour: int, minute: int) -> int:
    return hour * MINUTES_PER_HOUR + minute


def _minutes_to_time_str(total_minutes: int) -> str:
    if total_minutes < 0 or total_minutes >= MINUTES_PER_DAY:
        raise ValueError("Time value must be within a single day")
    hours = total_minutes // MINUTES_PER_HOUR
    minutes = total_minutes % MINUTES_PER_HOUR
    return (
        f"{hours:0{TIME_FIELD_WIDTH}d}:"
        f"{minutes:0{TIME_FIELD_WIDTH}d}"
    )


def _make_due_dict(offset_days: int, start_minutes: int, duration_minutes: int) -> dict[str, Any]:
    end_minutes = start_minutes + duration_minutes
    if end_minutes >= MINUTES_PER_DAY:
        raise ValueError("Task end_time exceeds the day boundary")
    return {
        "offset_days": offset_days,
        "start_time": _minutes_to_time_str(start_minutes),
        "end_time": _minutes_to_time_str(end_minutes),
    }


def _duration_weight(duration: int) -> float:
    if duration < SHORT_DURATION_THRESHOLD_MINUTES:
        return SHORT_DURATION_WEIGHT

    decay = (duration - SHORT_DURATION_THRESHOLD_MINUTES) * DURATION_WEIGHT_DECAY_PER_MINUTE
    weight = LONG_DURATION_WEIGHT_START - decay
    if weight < LONG_DURATION_WEIGHT_END:
        return LONG_DURATION_WEIGHT_END
    return weight


def _build_duration_distribution() -> tuple[list[int], list[float]]:
    durations = list(range(DURATION_MIN_MINUTES, DURATION_MAX_MINUTES + 1))
    weights = [_duration_weight(duration) for duration in durations]
    return durations, weights


def _random_duration(rng: random.Random) -> int:
    durations, weights = _build_duration_distribution()
    return rng.choices(durations, weights=weights, k=1)[0]


def _random_fixed_duration(rng: random.Random) -> int:
    return rng.randint(DURATION_MIN_MINUTES, FIXED_DURATION_MAX_MINUTES)


def _random_priority(rng: random.Random) -> int:
    return rng.randint(PRIORITY_MIN, PRIORITY_MAX)


def _random_gap(rng: random.Random) -> int:
    """Generate a gap duration with 80% probability for main range, 20% for alternative."""
    if rng.random() < GAP_MAIN_RANGE_PROBABILITY:
        return rng.randint(GAP_MAIN_RANGE_MIN_MINUTES, GAP_MAIN_RANGE_MAX_MINUTES)
    else:
        return rng.randint(GAP_ALT_RANGE_MIN_MINUTES, GAP_ALT_RANGE_MAX_MINUTES)


def _random_deadline_offset(rng: random.Random) -> int:
    return rng.randint(DEADLINE_OFFSET_MIN_DAYS, DEADLINE_OFFSET_MAX_DAYS)


def _build_task(
    *,
    content: str,
    priority: int,
    due: dict[str, Any],
    labels: list[str] | None,
    deadline_offset: int | None,
    gap_before_task: int | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "content": content,
        "priority": priority,
        "due": due,
        "copies": COPIES_DEFAULT,
    }

    if labels:
        task["labels"] = list(labels)

    if deadline_offset is not None:
        task["deadline"] = {"offset_days": deadline_offset}

    if gap_before_task is not None:
        task["gap_before_task"] = gap_before_task

    return task


def _init_fixed_intervals(window_start: int, window_end: int) -> dict[int, list[tuple[int, int]]]:
    end_day = FIXED_WINDOW_START_OFFSET_DAYS + FIXED_WINDOW_DAYS
    intervals: dict[int, list[tuple[int, int]]] = {}
    for day_offset in range(FIXED_WINDOW_START_OFFSET_DAYS, end_day):
        intervals[day_offset] = [(window_start, window_end)]
    return intervals


def _collect_fixed_candidates(
    intervals_by_day: dict[int, list[tuple[int, int]]],
    duration: int,
) -> list[tuple[int, int, int, int]]:
    candidates: list[tuple[int, int, int, int]] = []
    for day_offset, intervals in intervals_by_day.items():
        for index, (interval_start, interval_end) in enumerate(intervals):
            if interval_end - interval_start >= duration:
                candidates.append((day_offset, index, interval_start, interval_end))
    return candidates


def _apply_fixed_gap(
    intervals: list[tuple[int, int]],
    index: int,
    start: int,
    end: int,
) -> None:
    interval_start, interval_end = intervals.pop(index)

    block_start = start - FIXED_MIN_GAP_MINUTES
    block_end = end + FIXED_MIN_GAP_MINUTES

    if block_start < interval_start:
        block_start = interval_start
    if block_end > interval_end:
        block_end = interval_end

    if block_start > interval_start:
        intervals.append((interval_start, block_start))
    if block_end < interval_end:
        intervals.append((block_end, interval_end))


def _generate_fixed_tasks(count: int, rng: random.Random) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    window_start = _time_to_minutes(FIXED_WINDOW_START_HOUR, FIXED_WINDOW_START_MINUTE)
    window_end = _time_to_minutes(FIXED_WINDOW_END_HOUR, FIXED_WINDOW_END_MINUTE)
    window_size = window_end - window_start
    if FIXED_DURATION_MAX_MINUTES > window_size:
        raise ValueError("Fixed task duration exceeds fixed window size")

    intervals_by_day = _init_fixed_intervals(window_start, window_end)
    assigned_counts = {day_offset: 0 for day_offset in intervals_by_day}

    for _ in range(count):
        duration = _random_fixed_duration(rng)

        candidates = _collect_fixed_candidates(intervals_by_day, duration)
        if not candidates:
            raise ValueError("Not enough fixed-window capacity for the requested tasks")

        min_assigned = min(assigned_counts[candidate[0]] for candidate in candidates)
        balanced_candidates = [
            candidate for candidate in candidates if assigned_counts[candidate[0]] == min_assigned
        ]
        day_offset, interval_index, interval_start, interval_end = rng.choice(balanced_candidates)

        latest_start = interval_end - duration
        start_minutes = rng.randint(interval_start, latest_start)
        end_minutes = start_minutes + duration

        due = _make_due_dict(day_offset, start_minutes, duration)
        gap = _random_gap(rng)
        task = _build_task(
            content=FIXED_TASK_CONTENT,
            priority=FIXED_PRIORITY,
            due=due,
            labels=FIXED_TASK_LABELS,
            deadline_offset=None,
            gap_before_task=gap,
        )
        tasks.append(task)
        assigned_counts[day_offset] += 1

        intervals = intervals_by_day[day_offset]
        _apply_fixed_gap(intervals, interval_index, start_minutes, end_minutes)

    return tasks


def _generate_flexible_tasks(count: int, rng: random.Random) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    due_start_minutes = _time_to_minutes(DUE_START_HOUR, DUE_START_MINUTE)

    for _ in range(count):
        duration = _random_duration(rng)
        priority = _random_priority(rng)

        if rng.random() < NO_DEADLINE_PROBABILITY:
            content = FLEX_CONTENT_NO_DEADLINE_TEMPLATE.format(duration=duration)
            deadline_offset = None
        else:
            deadline_offset = _random_deadline_offset(rng)
            content = FLEX_CONTENT_WITH_DEADLINE_TEMPLATE.format(
                duration=duration, days=deadline_offset
            )

        due = _make_due_dict(DUE_OFFSET_DAYS, due_start_minutes, duration)
        gap = _random_gap(rng)
        task = _build_task(
            content=content,
            priority=priority,
            due=due,
            labels=FLEX_TASK_LABELS if FLEX_TASK_LABELS else None,
            deadline_offset=deadline_offset,
            gap_before_task=gap,
        )
        tasks.append(task)

    return tasks


def _build_seed(fixed_count: int, flexible_count: int, rng: random.Random) -> dict[str, Any]:
    tasks = _generate_fixed_tasks(fixed_count, rng)
    tasks.extend(_generate_flexible_tasks(flexible_count, rng))
    return {
        "project_name": PROJECT_NAME,
        "tasks": tasks,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a task seed JSON file for scheduler tests."
    )
    parser.add_argument(
        "output_path",
        type=Path,
        help="Path to write the generated JSON seed file.",
    )
    parser.add_argument(
        "fixed_count",
        type=int,
        help="Number of fixed tasks to generate.",
    )
    parser.add_argument(
        "flexible_count",
        type=int,
        help="Number of schedulable tasks to generate.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.fixed_count < 0 or args.flexible_count < 0:
        raise ValueError("Task counts must be non-negative")

    output_path: Path = args.output_path
    if not output_path.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {output_path.parent}")

    rng = random.Random()
    if RNG_SEED is not None:
        rng.seed(RNG_SEED)

    seed = _build_seed(args.fixed_count, args.flexible_count, rng)

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(seed, handle, indent=JSON_INDENT)
        handle.write("\n")


if __name__ == "__main__":
    main()
