"""Todoist webhook receiver component.

This module exposes an HTTP endpoint that can receive Todoist webhook payloads.
When a webhook request is received, it fetches the tasks planned for the next 14
days using the official Todoist SDK and then calls a user-supplied callback with
those tasks.

Example usage:

    def handle_tasks(tasks: list[Task]) -> None:
        for t in tasks:
            print(t.content)

    server = TodoistWebhookServer(
        api_token="<TODOIST_API_TOKEN>",
        client_secret="<TODOIST_CLIENT_SECRET>",
        on_tasks_fetched=handle_tasks,
    )
    server.run(host="0.0.0.0", port=8080)

Todoist webhooks send an `X-Todoist-Hmac-SHA256` header; we validate the payload
against that header to ensure the request came from Todoist.

Note: Todoist will retry webhook deliveries if the endpoint returns a non-2xx
status code, so this server always returns HTTP 200 even if signature verification
fails or task fetching fails. Instead, failures are logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
import os
from typing import Callable, Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
level_name = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, level_name, logging.INFO))

@dataclass(frozen=True)
class TodoistWebhookConfig:
    client_secret: str
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/"


class TodoistWebhookServer:
    """A minimal webhook receiver that polls Todoist when a webhook is received."""

    def __init__(
        self,
        client_secret: str,
        on_webhook: Callable[[], None],
        integration_user_id: str,
        host: str = "0.0.0.0",
        port: int = 8080,
        path: str = "/",
    ) -> None:
        """Create a new webhook server.

        Args:
            client_secret: Todoist app client secret; used to validate webhook signatures.
            on_webhook: Callback invoked when a webhook is received.
            integration_user_id: ID of the integration user to ignore events from.
            host: Host to bind the HTTP server to.
            port: Port to run the HTTP server on.
            path: HTTP path on which Todoist will send webhook events.
            upcoming_days_query: Todoist query used to fetch tasks (e.g. "(overdue | 14 days)").
        """
        self._config = TodoistWebhookConfig(
            client_secret=client_secret,
            host=host,
            port=port,
            path=path,
        )
        self._on_webhook = on_webhook
        self._integration_user_id = integration_user_id

        self._app = FastAPI()
        self._register_routes()

    def _register_routes(self) -> None:
        @self._app.post(self._config.path)
        async def webhook_endpoint(
            request: Request,
            x_todoist_hmac_sha256: Optional[str] = Header(None),
            x_todoist_delivery_id: Optional[str] = Header(None),
        ) -> PlainTextResponse:
            body = await request.body()
            # logger.debug("Received webhook request with body=%s", body) # TEMP
            # logger.debug("Received webhook delivery id=%s", x_todoist_delivery_id)

            if not x_todoist_hmac_sha256:
                logger.warning("Missing X-Todoist-Hmac-SHA256 header")
                return PlainTextResponse("OK", status_code=200)

            if not self._verify_signature(body, x_todoist_hmac_sha256):
                logger.warning("Invalid Todoist webhook signature")
                return PlainTextResponse("OK", status_code=200)

            body_obj = await request.json()

            # Ignore events triggered by integration user to avoid infinite loops
            event_initiator_id = body_obj.get("initiator", {}).get("id")
            if event_initiator_id == self._integration_user_id:
                logger.debug("Ignoring webhook event triggered by integration user")
                return PlainTextResponse("OK", status_code=200)

            # Skip events triggered by tasks without duration
            event_data = body_obj.get("event_data", {})
            if event_data.get("duration") is None:
                logger.debug(
                    f"Skipping webhook event without duration (task {event_data.get('content')})"
                )
                return PlainTextResponse("OK", status_code=200)

            # NOTE: this might cause problem if the callback takes a long time to execute, so Todoist will timeout the request and retry it later.
            self._on_webhook()

            return PlainTextResponse("OK", status_code=200)

    def _verify_signature(self, body: bytes, signature_header: str) -> bool:
        """Verify Todoist webhook signature.

        Todoist sends an `X-Todoist-Hmac-SHA256` header which contains a base64 encoded
        HMAC-SHA256 of the raw request body signed with your app's client secret.
        """
        computed_digest = hmac.new(
            self._config.client_secret.encode("utf-8"), body, hashlib.sha256
        ).digest()
        expected = base64.b64encode(computed_digest).decode("utf-8")
        return hmac.compare_digest(expected, signature_header)

    def run(self) -> None:
        """Run the webhook HTTP server."""
        import uvicorn

        uvicorn.run(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="info",
        )
