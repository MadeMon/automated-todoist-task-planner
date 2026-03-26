"""Application entrypoint that wires webhook -> planner -> Todoist updates."""

from __future__ import annotations

import logging
import os
from typing import Iterable, cast

from todoist_api_python.models import Task

from .planners.base_planner import BasePlanner
from .planners.mock_planner import MockPlanner
from .todoist_helper import is_task_fixed


from .todoist_client import TodoistTaskClient
from .todoist_webhook_server import TodoistWebhookServer

UPCOMING_TASKS_QUERY = "!today & (overdue | 14 days)"

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
    required_vars = ["TODOIST_API_TOKEN", "TODOIST_CLIENT_SECRET", "TODOIST_INTEGRATION_USER_ID"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    _verify_env_vars()

    client_secret = cast(str, os.getenv("TODOIST_CLIENT_SECRET"))
    api_token = cast(str, os.getenv("TODOIST_API_TOKEN"))
    integration_user_id = cast(str, os.getenv("TODOIST_INTEGRATION_USER_ID"))

    planner: BasePlanner = MockPlanner()
    todoist_client = TodoistTaskClient(api_token=api_token)

    def on_webhook() -> None:
        tasks = todoist_client.fetch_tasks_with_duration_due_soon_or_overdue(
            query=UPCOMING_TASKS_QUERY
        )

        fixed_tasks, flexible_tasks = _partition_tasks(tasks)
        
        planning_result = planner.plan(flexible_tasks,fixed_tasks)
        updated_tasks = todoist_client.update_tasks(planning_result)
        logger.info(
            "Fetched %d tasks, scheduled %d tasks, failed %d tasks, applied %d updates",
            len(tasks),
            len([scheduled_task for day in planning_result.schedule.days for scheduled_task in day]),
            len(planning_result.failed_to_schedule),
            len(updated_tasks),
        )

    server = TodoistWebhookServer(
        client_secret=client_secret,
        on_webhook=on_webhook,
        host=os.getenv("TODOIST_HOST", "0.0.0.0"),
        port=int(os.getenv("TODOIST_PORT", 8080)),
        path=os.getenv("TODOIST_PATH", "/"),
        integration_user_id=integration_user_id,
    )
    server.run()


if __name__ == "__main__":
    main()
