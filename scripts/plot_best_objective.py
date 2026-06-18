#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\"").strip("'")
    match = _FLOAT_RE.search(cleaned)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\"").strip("'")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned))
        except ValueError:
            return None


def _load_runs(csv_path: Path) -> tuple[OrderedDict[str, list[tuple[int, float]]], int]:
    runs: OrderedDict[str, list[tuple[int, float]]] = OrderedDict()
    skipped = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            metric = (row.get("metric") or "").strip()
            if metric and metric != "best_objective":
                continue

            run_name = (row.get("Run") or "").strip()
            if not run_name:
                skipped += 1
                continue

            step = _parse_int(row.get("step"))
            value = _parse_float(row.get("value"))
            if step is None or value is None:
                skipped += 1
                continue

            runs.setdefault(run_name, []).append((step, value))

    return runs, skipped


def _sorted_pairs(pairs: Iterable[tuple[int, float]]) -> tuple[list[int], list[float]]:
    ordered = sorted(pairs, key=lambda item: item[0])
    steps = [item[0] for item in ordered]
    values = [item[1] for item in ordered]
    return steps, values


def _plot_runs(
    runs: OrderedDict[str, list[tuple[int, float]]],
    output_path: Path,
    show: bool,
) -> None:
    if not runs:
        raise ValueError("No valid rows found in CSV.")

    fig, ax = plt.subplots(figsize=(16, 7))
    for run_name, pairs in runs.items():
        steps, values = _sorted_pairs(pairs)
        ax.plot(steps, values, label=run_name)

    ax.set_xlabel("Step")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=15)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)

    if show:
        plt.show()

    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plot best objective values from an MLflow CSV export as lines per Run."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("best_objective.csv"),
        help="Path to the CSV file (default: best_objective.csv).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("best_objective_plot.png"),
        help="Output image file (default: best_objective_plot.png).",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the plot but do not open a window.",
    )
    args = parser.parse_args()

    csv_path = args.input
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    runs, skipped = _load_runs(csv_path)
    _plot_runs(runs, args.output, show=not args.no_show)

    print(
        f"Plotted {len(runs)} runs with {skipped} skipped rows. "
        f"Saved to {args.output}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
