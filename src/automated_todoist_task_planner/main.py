"""Application entrypoint that wires webhook -> planner -> Todoist updates."""

from __future__ import annotations

import argparse
import logging
import os

from todoist_api_python.models import Task

from .mock_planner import MockPlanner
from .todoist_client import TodoistTaskClient
from .todoist_webhook_server import TodoistWebhookServer


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level_name, logging.INFO))


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run webhook receiver + mock planner + selective Todoist updates."
    )
    parser.add_argument("--api-token", required=True, help="Todoist API token")
    parser.add_argument(
        "--client-secret",
        required=True,
        help="Todoist app client secret for verifying webhook requests",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8080, help="Port to run the server on")
    parser.add_argument(
        "--path",
        default="/payload",
        help="HTTP path on which Todoist webhook events are received",
    )
    parser.add_argument(
        "--query",
        default="(overdue | 14 days)",
        help="Todoist query used to fetch candidate tasks",
    )
    parser.add_argument(
        "--integration-user-id",
        required=True,
        help="ID of the integration user to ignore events from",
    )
    return parser


def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)

    parser = _build_argument_parser()
    args = parser.parse_args()

    # CONTINUE: implement the actual planner
    planner = MockPlanner()
    todoist_client = TodoistTaskClient(api_token=args.api_token)

    def on_tasks_fetched(tasks: list[Task]) -> None:
        planned_tasks = planner.plan(tasks)
        updated_tasks = todoist_client.update_tasks(planned_tasks)
        logger.info(
            "Fetched %d tasks, planned %d tasks, applied %d updates",
            len(tasks),
            len(planned_tasks),
            len(updated_tasks),
        )

    server = TodoistWebhookServer(
        api_token=args.api_token,
        client_secret=args.client_secret,
        on_tasks_fetched=on_tasks_fetched,
        host=args.host,
        port=args.port,
        path=args.path,
        upcoming_days_query=args.query,
        integration_user_id=args.integration_user_id,
    )
    server.run()


if __name__ == "__main__":
    main()
