from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from .planners.base_planner import PlanningResult
from .todoist_helper import is_task_fixed


_PRIORITY_COLORS = {
    1: "red",
    2: "orange",
    3: "blue",
    4: "gray",
}


@dataclass(frozen=True)
class PlotStyle:
    column_width: float = 0.9
    column_padding: float = 0.05
    task_alpha: float = 0.5
    grid_alpha: float = 0.3
    label_fontsize: int = 9


def _minutes_since_start(start_time: time, moment: datetime) -> int:
    return moment.hour * 60 + moment.minute - (start_time.hour * 60 + start_time.minute)


def _format_time_labels(start_time: time, minutes: Iterable[int]) -> list[str]:
    base = datetime.combine(datetime.today().date(), start_time)
    return [(base + timedelta(minutes=offset)).strftime("%H:%M") for offset in minutes]


def _truncate_title(title: str, max_chars: int = 30) -> str:
    if len(title) <= max_chars:
        return title
    return f"{title[: max_chars - 1]}…"


def plot_schedule_to_file(
    result: PlanningResult,
    output_path: str | Path,
    style: PlotStyle | None = None,
) -> Path:
    schedule = result.schedule
    num_days = schedule.num_days
    if style is None:
        style = PlotStyle()

    total_minutes = schedule.total_minutes_per_day
    if total_minutes <= 0:
        raise ValueError("Schedule productive window must be positive.")

    fig_width = max(6.0, num_days * 2.0)
    fig_height = max(6.0, total_minutes / 120.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    for day_index in range(num_days):
        day_tasks = sorted(schedule.days[day_index], key=lambda t: t.start)
        for scheduled in day_tasks:
            start_minutes = _minutes_since_start(schedule.start_time, scheduled.start)
            end_minutes = _minutes_since_start(schedule.start_time, scheduled.end)

            clipped_start = max(0, start_minutes)
            clipped_end = min(total_minutes, end_minutes)
            if clipped_end <= clipped_start:
                continue

            task = scheduled.task
            priority = getattr(task, "priority", None)
            color = _PRIORITY_COLORS.get(priority, "gray")

            x = day_index - 0.5 + style.column_padding
            width = style.column_width
            y = clipped_start
            height = clipped_end - clipped_start

            is_fixed = is_task_fixed(task)
            edgecolor = "black" if is_fixed else "none"
            linewidth = 1.5 if is_fixed else 0.0

            ax.add_patch(
                Rectangle(
                    (x, y),
                    width,
                    height,
                    facecolor=color,
                    edgecolor=edgecolor,
                    linewidth=linewidth,
                    alpha=style.task_alpha,
                )
            )

            title = _truncate_title(getattr(task, "content", ""))
            ax.text(
                x + width / 2,
                y + height / 2,
                title,
                ha="center",
                va="center",
                fontsize=style.label_fontsize,
                color="black",
                wrap=True,
            )

    ax.set_xlim(-0.5, num_days - 0.5)
    ax.set_ylim(total_minutes, 0)
    ax.set_xticks(range(num_days))
    ax.set_xticklabels([str(day + 1) for day in range(num_days)])

    tick_step = 60
    ticks = list(range(0, total_minutes + 1, tick_step))
    ax.set_yticks(ticks)
    ax.set_yticklabels(_format_time_labels(schedule.start_time, ticks))

    ax.set_xlabel("Day")
    ax.set_ylabel("Time")
    ax.grid(axis="y", linestyle="--", alpha=style.grid_alpha)
    ax.set_axisbelow(True)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)

    return output_path
