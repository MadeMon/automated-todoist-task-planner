from dataclasses import dataclass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from todoist_api_python.models import Task
    from datetime import datetime


@dataclass
class ScheduledTask:
    start: "datetime"
    end: "datetime"
    task: "Task"

    def __copy__(self):
        return ScheduledTask(
            start=self.start,
            end=self.end,
            task=self.task,
        )
