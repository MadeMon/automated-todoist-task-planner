from copy import copy
from datetime import datetime, timedelta, time
from typing import List, TYPE_CHECKING, Hashable

from .todoist_helper import (
    get_task_deadline_date,
    get_task_due_date,
    get_task_duration_minutes,
    is_task_fixed,
)
from .scheduled_task import ScheduledTask

if TYPE_CHECKING:
    from todoist_api_python.models import Task


class TasksSchedule:
    """
    Tracks scheduled tasks per day within a configured productive time window.

    Manages scheduling of tasks across multiple days, ensuring they fit within
    the specified productive time range (e.g., 9 AM - 6 PM).
    """

    def __init__(
        self,
        plan_tasks_from: datetime,
        start_time: time,
        end_time: time,
        fixed_tasks: list["Task"],
        num_days: int = 14,
    ):
        """
        Initialize the TasksSchedule.

        Args:
            start_time: Start of the productive time window (e.g., time(9, 0))
            end_time: End of the productive time window (e.g., time(18, 0))
            fixed_tasks: List of tasks with fixed schedule
            num_days: Number of days to schedule tasks into (default: 14)
        """
        self.start_time = start_time
        self.end_time = end_time
        self.num_days = num_days
        self.start_date = plan_tasks_from.date()
        self.fixed_tasks = fixed_tasks

        # Calculate total available minutes per day
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        self.total_minutes_per_day = end_minutes - start_minutes

        # Initialize list of days, each day is a list of ScheduledTasks
        self.days: List[List[ScheduledTask]] = [[] for _ in range(num_days)]
        self.__task_index: dict[Hashable, tuple[int, ScheduledTask]] = {}

        self.__save_fixed_tasks(fixed_tasks)

    def get_start_of_planning_range(self) -> datetime:
        """
        Get the start datetime of the planning range.

        Returns:
            Datetime representing the start of the planning range (combination of start_date and start_time)
        """
        return datetime.combine(self.start_date, self.start_time)
    
    def get_end_of_planning_range(self) -> datetime:
        """
        Get the end datetime of the planning range.

        Returns:
            Datetime representing the end of the planning range (start_date + num_days combined with end_time)
        """
        end_date = self.start_date + timedelta(days=self.num_days)
        return datetime.combine(end_date, self.end_time)
        

    def __copy__(self):
        # Create a new instance of TasksSchedule

        new_schedule = TasksSchedule(
            plan_tasks_from=datetime.combine(self.start_date, self.start_time),
            start_time=self.start_time,
            end_time=self.end_time,
            fixed_tasks=self.fixed_tasks,
            num_days=self.num_days,
        )

        for day in range(self.num_days):
            for scheduled_task in self.days[day]:
                if scheduled_task.task in self.fixed_tasks:
                    continue  # Fixed tasks are already saved in the new schedule during initialization
                new_schedule.add_scheduled_task(day, copy(scheduled_task))

        return new_schedule

    def __index_scheduled_task(self, day: int, scheduled_task: ScheduledTask) -> None:
        task_key = scheduled_task.task.id
        self.__task_index[task_key] = (day, scheduled_task)

    def add_scheduled_task(self, day: int, scheduled_task: ScheduledTask) -> None:
        self.days[day].append(scheduled_task)
        self.__index_scheduled_task(day, scheduled_task)

    def __save_fixed_tasks(self, fixed_tasks: list["Task"]):
        """
        Save fixed tasks into the schedule.

        This method should be called during initialization to populate the schedule
        with tasks that have fixed due dates and times.

        Args:
            fixed_tasks: List of Todoist Task objects with fixed schedules
        """
        for task in fixed_tasks:
            task_due_date = get_task_due_date(task)

            # NOTE - Tasks without due date should be already filtered out by the TodoistClient
            if task_due_date is None or task.duration is None:
                continue  # Skip tasks without a valid due date or duration

            # Calculate the day index based on the task's due date
            day_index = (task_due_date.date() - self.start_date).days

            if day_index < 0 or day_index >= self.num_days:
                continue  # Skip tasks that are outside the scheduling range

            # Schedule the task at its due time
            scheduled_task = ScheduledTask(
                start=task_due_date,
                end=task_due_date + timedelta(minutes=get_task_duration_minutes(task)),
                task=task,
            )
            self.add_scheduled_task(day_index, scheduled_task)

    def get_available_time(self, day: int, ignore_scheduled_tasks: bool = False) -> int:
        """
        Get the available time in minutes for a specific day.

        Args:
            day: Day index (0-based, where 0 is the first day)
            ignore_scheduled_tasks: Whether to ignore existing scheduled tasks when calculating available time

        Returns:
            Number of available minutes in the day

        Raises:
            IndexError: If day index is out of range
        """
        if day < 0 or day >= self.num_days:
            raise IndexError(f"Day {day} is out of range [0, {self.num_days - 1}]")

        # Calculate total scheduled minutes in the day
        scheduled_minutes = sum(
            int((sched_task.end - sched_task.start).total_seconds() / 60) if not ignore_scheduled_tasks or is_task_fixed(sched_task.task) else 0  for sched_task in self.days[day]
        )

        return self.total_minutes_per_day - scheduled_minutes

    def get_first_available_slot_in_day(
        self,
        day: int,
        task: "Task",
        ignore_scheduled_tasks: bool = False,
        ignore_task: "Task | None" = None,
    ) -> datetime:
        """
        Get the first available slot for a task in a specific day.

        Args:
            day: Day index (0-based)
            task: Todoist Task object (must have duration set)
            ignore_scheduled_tasks: Whether to ignore existing scheduled tasks when finding available slots
            ignore_task: Task to ignore when checking occupied slots (typically the task being evaluated)

        Returns:
            Datetime of the first available slot for the task

        Raises:
            IndexError: If day index is out of range
            ValueError: If task has no duration or duration exceeds available time
        """
        if day < 0 or day >= self.num_days:
            raise IndexError(f"Day {day} is out of range [0, {self.num_days - 1}]")

        task_duration = get_task_duration_minutes(task)

        available_time = self.get_available_time(day, ignore_scheduled_tasks=ignore_scheduled_tasks)
        if task_duration > available_time:
            raise ValueError(
                f"Task duration ({task_duration} minutes) exceeds available time "
                f"({available_time} minutes) in day {day}"
            )

        def should_include(scheduled_task: ScheduledTask) -> bool:
            if ignore_task is not None and scheduled_task.task.id == ignore_task.id:
                return False
            if ignore_scheduled_tasks and not is_task_fixed(scheduled_task.task):
                return False
            return True

        # Sort existing tasks by start time
        sorted_tasks = sorted(
            [scheduled_task for scheduled_task in self.days[day] if should_include(scheduled_task)],
            key=lambda t: t.start,
        )

        # Get the date for this day
        day_date = self.start_date + timedelta(days=day)

        # Find first available slot
        current_time = self.start_time

        for scheduled_task in sorted_tasks:
            # Check if task fits before the next scheduled task
            slot_start_datetime = datetime.combine(day_date, current_time)
            slot_end_datetime = slot_start_datetime + timedelta(minutes=task_duration)

            if slot_end_datetime.time() <= scheduled_task.start.time():
                return slot_start_datetime

            # Move current_time to after the scheduled task
            current_time = scheduled_task.end.time()

        # Check if task fits after the last scheduled task
        slot_start_datetime = datetime.combine(day_date, current_time)
        slot_end_datetime = slot_start_datetime + timedelta(minutes=task_duration)

        if slot_end_datetime.time() <= self.end_time:
            return slot_start_datetime
        else:
            raise ValueError(f"Could not find available slot for task in day {day}")

    def schedule_task_to_first_available_slot_in_day(
        self, day: int, task: "Task"
    ) -> ScheduledTask:
        """
        Schedule a task to the first available slot in a specific day.

        Args:
            day: Day index (0-based)
            task: Todoist Task object (must have duration set)

        Returns:
            ScheduledTask object that was created and scheduled

        Raises:
            IndexError: If day index is out of range
            ValueError: If task has no duration or duration exceeds available time
        """
        slot_start = self.get_first_available_slot_in_day(
            day, task
        )  # This will raise exceptions if scheduling is not possible
        slot_end = slot_start + timedelta(minutes=get_task_duration_minutes(task))

        scheduled = ScheduledTask(start=slot_start, end=slot_end, task=task)
        self.add_scheduled_task(day, scheduled)
        return scheduled

    # TODO ideally remove
    def get_earliest_feasible_slot(
        self,
        task: "Task",
        ignore_scheduled_tasks: bool = False,
        ignore_task: "Task | None" = None,
    ) -> datetime:
        """
        Get the earliest feasible slot for a task across all days.

        Args:
            task: Todoist Task object (must have duration set)
            ignore_scheduled_tasks: Whether to ignore existing scheduled tasks
            ignore_task: Task to ignore when checking occupied slots
        """
        for day in range(self.num_days):
            try:
                return self.get_first_available_slot_in_day(
                    day,
                    task,
                    ignore_scheduled_tasks=ignore_scheduled_tasks,
                    ignore_task=ignore_task,
                )
            except ValueError:
                continue

        raise ValueError(
            f"Could not find feasible slot for task '{task.content}' in any day"
        )

    def delete_task(self, task: "Task") -> ScheduledTask:
        """
        Delete a scheduled task by Todoist Task object.

        Uses a private index for fast lookup of the ScheduledTask reference.

        Args:
            task: Todoist Task object

        Returns:
            The removed ScheduledTask

        Raises:
            ValueError: If task cannot be identified or is not scheduled
        """

        indexed_value = self.__task_index.get(task.id)
        if indexed_value is None:
            raise ValueError(f"Task '{task.content}' is not scheduled")

        day, scheduled_task = indexed_value

        try:
            self.days[day].remove(scheduled_task)
        except ValueError as exc:
            # Keep index consistent if day list was modified unexpectedly.
            self.__task_index.pop(task.id, None)
            raise ValueError(f"Task '{task.content}' is not scheduled") from exc

        self.__task_index.pop(task.id, None)
        return scheduled_task

    def schedule_task_to_first_available_slot_in_any_day(
        self, task: "Task", respect_deadline: bool = False
    ) -> ScheduledTask:
        """
        Schedule a task to the first available slot in any day.

        Args:
            task: Todoist Task object (must have duration set)

        Returns:
            ScheduledTask object that was created and scheduled

        Raises:
            ValueError: If task has no duration or no day has enough available time
        """

        slots = self.get_slot_per_days(
            task, return_available_days=1, respect_deadline=respect_deadline
        )

        if len(slots) == 0:
            raise ValueError(
                f"No available slot found for task '{task.content}' in any day"
            )

        day, slot = slots[0]

        scheduled_task = ScheduledTask(
            start=slot,
            end=slot + timedelta(minutes=get_task_duration_minutes(task)),
            task=task,
        )
        self.add_scheduled_task(day, scheduled_task)

        return scheduled_task

    def schedule_task_to_first_available_slot_balance_days(
        self, task: "Task", respect_deadline: bool = False
    ) -> ScheduledTask:
        """
        Schedule a task to the first available slot across days, prioritizing
        days with the most available time.

        Sorts days by available time in descending order and iteratively tries
        to insert the task into days, starting with those having the most available time.

        Args:
            task: Todoist Task object (must have duration set)
            respect_deadline: If True, the scheduling will respect the task's deadline.
        Returns:
            ScheduledTask object that was created and scheduled

        Raises:
            ValueError: If task has no duration or no day has enough available time
        """
        task_duration = get_task_duration_minutes(task)

        # Create list of (day_index, available_time) and sort by available time (descending)
        day_availability = [
            (day_idx, self.get_available_time(day_idx))
            for day_idx in range(self.num_days)
        ]
        day_availability.sort(key=lambda x: x[1], reverse=True)

        # Try to schedule task in each day, starting with most available time
        for day_idx, available_time in day_availability:
            task_deadline_date = get_task_deadline_date(task)
            if respect_deadline and task_deadline_date is not None:
                task_deadline_day = (task_deadline_date - self.start_date).days
                if day_idx > task_deadline_day:
                    continue  # Skip days after the task's deadline
            if available_time < task_duration:
                # If current day doesn't have enough time, no future day will either
                raise ValueError(
                    f"Task duration ({task_duration} minutes) exceeds available time "
                    f"in all remaining days. Best available: {available_time} minutes in day {day_idx}"
                )

            try:
                return self.schedule_task_to_first_available_slot_in_day(day_idx, task)
            except ValueError:
                # This day doesn't have a suitable slot, try next day
                continue

        raise ValueError(
            f"Could not schedule task with duration {task_duration} minutes "
            f"in any of the {self.num_days} days"
        )

    def get_scheduled_tasks(self, include_fixed: bool = True) -> List[ScheduledTask]:
        """
        Get a list of all scheduled tasks across all days.

        Returns:
            List of ScheduledTask objects that are currently scheduled
        """
        return [
            task
            for day in self.days
            for task in day
            if include_fixed or not is_task_fixed(task.task)
        ]

    def get_slot_per_days(
        self,
        task: "Task",
        return_available_days: int | None = None,
        respect_deadline: bool = False,
        ignore_scheduled_tasks: bool = False,
        ignore_task: "Task | None" = None,
    ) -> List[tuple[int, datetime]]:
        """
        Get the first available slot for a task in every day.

        Args:
            task: Todoist Task object (must have duration set)
            return_available_days: If set, the search stops after finding available slots in this many days. If None, checks all days.
            respect_deadline: If True, the search will respect the task's deadline.
        """

        schedule_before_day = self.num_days

        if respect_deadline:
            task_deadline = get_task_deadline_date(task)
            if task_deadline is not None:
                if task_deadline < self.start_date:
                    raise ValueError(
                        f"Task '{task.content}' has a past deadline and cannot be scheduled"
                    )
                else:
                    schedule_before_day = min(
                        schedule_before_day,
                        (task_deadline - self.start_date).days + 1,
                    )

        available_slots = []
        for day in range(schedule_before_day):
            try:
                slot = self.get_first_available_slot_in_day(day, task, ignore_scheduled_tasks=ignore_scheduled_tasks, ignore_task=ignore_task)
                available_slots.append((day, slot))
                if (
                    return_available_days is not None
                    and len(available_slots) >= return_available_days
                ):
                    return available_slots
            except ValueError:
                continue  # No available slot in this day, check next day

        return available_slots
