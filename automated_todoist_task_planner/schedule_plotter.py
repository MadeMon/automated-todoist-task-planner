from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.patches import Rectangle

from .planners.base_planner import PlanningResult
from .todoist_helper import (
    get_task_deadline_date,
    get_task_duration_minutes,
    is_task_fixed,
)


_PRIORITY_COLORS = {
    4: "red",
    3: "orange",
    2: "blue",
    1: "gray",
}


@dataclass(frozen=True)
class PlotStyle:
    column_width: float = 0.9
    column_padding: float = 0.05
    task_alpha: float = 0.5
    grid_alpha: float = 0.3
    label_fontsize: int = 9
    failed_tasks_label_fontsize: int = 20
    day_bar_minutes: int = 12
    day_bar_offset_minutes: int = 4
    deadline_strip_width: float = 0.08
    failed_section_gap_minutes: int = 100
    failed_task_min_minutes: int = 15
    failed_task_height_minutes: int = 20
    failed_separator_width: float = 4.0
    failed_separator_offset_minutes: int = 12
    failed_label_offset_minutes: int = 28
    task_border_color: str = "black"
    task_border_width: float = 0.6
    fixed_task_hatch: str = "//"
    fixed_task_hatch_color: str = "black"


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
    last_day_with_tasks = 0
    for day_index, day_tasks in enumerate(schedule.days):
        if day_tasks:
            last_day_with_tasks = day_index
    num_days = max(1, last_day_with_tasks + 1)
    if style is None:
        style = PlotStyle()

    total_minutes = schedule.total_minutes_per_day
    if total_minutes <= 0:
        raise ValueError("Schedule productive window must be positive.")

    fig_width = max(6.0, num_days * 2.0)
    day_colors = cm.get_cmap("tab20", num_days)
    deadline_days: set[int] = set()
    for scheduled_task in schedule.get_scheduled_tasks(include_fixed=True):
        deadline_date = get_task_deadline_date(scheduled_task.task)
        if deadline_date is None:
            continue
        day_index = (deadline_date - schedule.start_date).days
        if 0 <= day_index < num_days:
            deadline_days.add(day_index)

    day_bar_height = min(style.day_bar_minutes, total_minutes)
    day_bar_area = (
        style.day_bar_offset_minutes + day_bar_height if deadline_days else 0
    )

    failed_tasks = result.failed_to_schedule
    failed_task_sizes = [
        max(get_task_duration_minutes(task), style.failed_task_min_minutes)
        for task in failed_tasks
    ]
    failed_section_gap = style.failed_section_gap_minutes if failed_tasks else 0
    failed_section_height = (
        failed_section_gap + max(failed_task_sizes) if failed_tasks else 0
    )
    max_minutes = total_minutes + day_bar_area + failed_section_height

    fig_height = max(6.0, max_minutes / 120.0)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    for day_index in sorted(deadline_days):
        day_color = day_colors(day_index)
        bar_x = day_index - 0.5 + style.column_padding
        bar_width = style.column_width
        bar_y = total_minutes + style.day_bar_offset_minutes
        ax.add_patch(
            Rectangle(
                (bar_x, bar_y),
                bar_width,
                day_bar_height,
                facecolor=day_color,
                edgecolor="none",
                alpha=1,
            )
        )

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
            edgecolor = style.task_border_color
            linewidth = style.task_border_width
            hatch = style.fixed_task_hatch if is_fixed else None

            rect = Rectangle(
                (x, y),
                width,
                height,
                facecolor=color,
                edgecolor=edgecolor,
                linewidth=linewidth,
                hatch=hatch,
                alpha=style.task_alpha,
            )
            ax.add_patch(rect)

            if is_fixed and style.fixed_task_hatch:
                ax.add_patch(
                    Rectangle(
                        (x, y),
                        width,
                        height,
                        facecolor="none",
                        edgecolor=style.fixed_task_hatch_color,
                        linewidth=0,
                        hatch=style.fixed_task_hatch,
                        alpha=1,
                    )
                )

            deadline_date = get_task_deadline_date(task)
            if deadline_date is not None:
                deadline_day = (deadline_date - schedule.start_date).days
                if 0 <= deadline_day < num_days:
                    strip_color = day_colors(deadline_day)
                    strip_width = min(style.deadline_strip_width, width)
                    ax.add_patch(
                        Rectangle(
                            (x, y),
                            strip_width,
                            height,
                            facecolor=strip_color,
                            edgecolor="none",
                            alpha=1,
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

    if failed_tasks:
        separator_y = total_minutes + day_bar_area + failed_section_gap / 2
        ax.axhline(
            separator_y,
            color=style.task_border_color,
            linewidth=style.failed_separator_width,
            xmin=0,
            xmax=1,
        )
        label_y = separator_y + style.failed_label_offset_minutes
        ax.text(
            -0.5 + style.column_padding,
            label_y,
            "Failed tasks",
            ha="left",
            va="center",
            fontsize=style.failed_tasks_label_fontsize,
            color="black",
        )

        failed_x = -0.5 + style.column_padding
        failed_width = num_days - 2 * style.column_padding
        failed_y = total_minutes + day_bar_area + failed_section_gap
        total_failed = sum(failed_task_sizes)
        current_x = failed_x

        for task, size in zip(failed_tasks, failed_task_sizes):
            priority = getattr(task, "priority", None)
            color = _PRIORITY_COLORS.get(priority, "gray")
            width = failed_width * (size / total_failed) if total_failed else 0
            height = size

            ax.add_patch(
                Rectangle(
                    (current_x, failed_y),
                    width,
                    height,
                    facecolor=color,
                    edgecolor=style.task_border_color,
                    linewidth=style.task_border_width,
                    alpha=style.task_alpha,
                )
            )

            deadline_date = get_task_deadline_date(task)
            if deadline_date is not None:
                deadline_day = (deadline_date - schedule.start_date).days
                if 0 <= deadline_day < num_days:
                    strip_color = day_colors(deadline_day)
                    strip_width = min(style.deadline_strip_width, width)
                    ax.add_patch(
                        Rectangle(
                            (current_x, failed_y),
                            strip_width,
                            height,
                            facecolor=strip_color,
                            edgecolor="none",
                            alpha=1,
                        )
                    )

            title = _truncate_title(getattr(task, "content", ""))
            ax.text(
                current_x + width / 2,
                failed_y + height / 2,
                title,
                ha="center",
                va="center",
                fontsize=style.label_fontsize,
                color="black",
                wrap=True,
            )
            current_x += width

    ax.set_xlim(-0.5, num_days - 0.5)
    ax.set_ylim(max_minutes, 0)
    ax.spines["bottom"].set_position(("data", total_minutes))
    ax.xaxis.set_ticks_position("bottom")
    ax.xaxis.set_label_position("bottom")
    ax.tick_params(axis="x", pad=6)
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
