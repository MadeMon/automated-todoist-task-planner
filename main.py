"""Application entrypoint that wires webhook -> planner -> Todoist updates."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import logging
import os
from typing import Iterable, cast

from todoist_api_python.models import Task


from automated_todoist_task_planner.planners import (
    BasePlanner,
    HeuristicPlanner,
    MockPlanner,
    LNSPlanner,
)
from automated_todoist_task_planner.todoist_helper import is_task_fixed


from automated_todoist_task_planner.todoist_client import TodoistTaskClient
from automated_todoist_task_planner.todoist_webhook_server import TodoistWebhookServer

UPCOMING_TASKS_QUERY = "!today & (overdue | 14 days)"

PLANNING_START_TIME = "00:00"  # Plan tasks into working hours by default, but this can be customized via environment variables.
PLANNING_END_TIME = "08:00"  # Plan tasks into working hours by default, but this can be customized via environment variables.
PLANNING_DAYS = 14  # Plan tasks due in next two weeks by default, but this can be customized via environment variables.
PLANNING_FROM_DATE_OFFSET_DAYS = 1  # Plan tasks from tomorrow by default, but this can be customized via environment variables.


def _partition_tasks(tasks: Iterable[Task]) -> tuple[list[Task], list[Task]]:
    fixed: list[Task] = []
    flexible: list[Task] = []
    for task in tasks:
        if is_task_fixed(task):
            fixed.append(task)
        else:
            flexible.append(task)
    return fixed, flexible


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level_name, logging.INFO))


def _verify_env_vars() -> None:
    required_vars = [
        "TODOIST_API_TOKEN",
        "TODOIST_CLIENT_SECRET",
        "TODOIST_INTEGRATION_USER_ID",
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )


def __parse_time(time_str: str) -> time:
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        raise ValueError(f"Invalid time format for '{time_str}'. Expected HH:MM.")


def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    _verify_env_vars()

    client_secret = cast(str, os.getenv("TODOIST_CLIENT_SECRET"))
    api_token = cast(str, os.getenv("TODOIST_API_TOKEN"))
    integration_user_id = cast(str, os.getenv("TODOIST_INTEGRATION_USER_ID"))

    # planner: BasePlanner = MockPlanner()
    # planner: BasePlanner = HeuristicPlanner()
    planner: BasePlanner = LNSPlanner()
    todoist_client = TodoistTaskClient(api_token=api_token)

    async def _run_planning_cycle() -> None:
        planning_from_date = datetime.now() + timedelta(
            days=PLANNING_FROM_DATE_OFFSET_DAYS
        )

        tasks = await todoist_client.fetch_tasks_with_duration_due_soon_or_overdue(
            query=UPCOMING_TASKS_QUERY
        )

        fixed_tasks, flexible_tasks = _partition_tasks(tasks)

        planning_result = planner.plan(
            planning_from_date=planning_from_date,
            start_time=__parse_time(PLANNING_START_TIME),
            end_time=__parse_time(PLANNING_END_TIME),
            plan_days=PLANNING_DAYS,
            flexible_tasks=flexible_tasks,
            fixed_tasks=fixed_tasks,
        )
        updated_tasks = await todoist_client.update_tasks(planning_result)
        logger.info(
            "Fetched %d tasks, scheduled %d tasks, failed %d tasks, applied %d updates",
            len(tasks),
            len(
                [
                    scheduled_task
                    for day in planning_result.schedule.days
                    for scheduled_task in day
                ]
            ),
            len(planning_result.failed_to_schedule),
            len(updated_tasks),
        )

    server = TodoistWebhookServer(
        client_secret=client_secret,
        on_webhook=_run_planning_cycle,
        host=os.getenv("TODOIST_HOST", "0.0.0.0"),
        port=int(os.getenv("TODOIST_PORT", 8080)),
        path=os.getenv("TODOIST_PATH", "/"),
        integration_user_id=integration_user_id,
    )
    server.run()


if __name__ == "__main__":
    main()
