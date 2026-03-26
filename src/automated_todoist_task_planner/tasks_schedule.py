from datetime import datetime, timedelta, time
from typing import List, TYPE_CHECKING

from .todoist_helper import get_task_due_date, get_task_duration_minutes
from .scheduled_task import ScheduledTask

if TYPE_CHECKING:
    from todoist_api_python.models import Task


class TasksSchedule:
    """
    Tracks scheduled tasks per day within a configured productive time window.
    
    Manages scheduling of tasks across multiple days, ensuring they fit within
    the specified productive time range (e.g., 9 AM - 6 PM).
    """
    
    def __init__(self, start_time: time, end_time: time, fixed_tasks: list["Task"], num_days: int = 14):
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
        self.start_date = datetime.now().date() + timedelta(days=1)
        
        # Calculate total available minutes per day
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        self.total_minutes_per_day = end_minutes - start_minutes
        
        # Initialize list of days, each day is a list of ScheduledTasks
        self.days: List[List[ScheduledTask]] = [[] for _ in range(num_days)]

        self.__save_fixed_tasks(fixed_tasks)

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
                task=task
            )
            self.days[day_index].append(scheduled_task)

    
    def get_available_time(self, day: int) -> int:
        """
        Get the available time in minutes for a specific day.
        
        Args:
            day: Day index (0-based, where 0 is the first day)
            
        Returns:
            Number of available minutes in the day
            
        Raises:
            IndexError: If day index is out of range
        """
        if day < 0 or day >= self.num_days:
            raise IndexError(f"Day {day} is out of range [0, {self.num_days - 1}]")
        
        # Calculate total scheduled minutes in the day
        scheduled_minutes = sum(
            int((task.end - task.start).total_seconds() / 60)
            for task in self.days[day]
        )
        
        return self.total_minutes_per_day - scheduled_minutes
    
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
        if day < 0 or day >= self.num_days:
            raise IndexError(f"Day {day} is out of range [0, {self.num_days - 1}]")
        
        task_duration = get_task_duration_minutes(task)
        
        if task_duration > self.get_available_time(day):
            raise ValueError(
                f"Task duration ({task_duration} minutes) exceeds available time "
                f"({self.get_available_time(day)} minutes) in day {day}"
            )
        
        # Sort existing tasks by start time
        sorted_tasks = sorted(self.days[day], key=lambda t: t.start)
        
        # Get the date for this day
        day_date = self.start_date + timedelta(days=day)
        
        # Find first available slot
        current_time = self.start_time
        
        for scheduled_task in sorted_tasks:
            # Check if task fits before the next scheduled task
            slot_start_datetime = datetime.combine(day_date, current_time)
            slot_end_datetime = slot_start_datetime + timedelta(minutes=task_duration)
            
            if slot_end_datetime.time() <= scheduled_task.start.time():
                # Task fits in this slot
                scheduled = ScheduledTask(
                    start=slot_start_datetime,
                    end=slot_end_datetime,
                    task=task
                )
                self.days[day].append(scheduled)
                return scheduled
            
            # Move current_time to after the scheduled task
            current_time = scheduled_task.end.time()
        
        # Check if task fits after the last scheduled task
        slot_start_datetime = datetime.combine(day_date, current_time)
        slot_end_datetime = slot_start_datetime + timedelta(minutes=task_duration)
        
        if slot_end_datetime.time() <= self.end_time:
            scheduled = ScheduledTask(
                start=slot_start_datetime,
                end=slot_end_datetime,
                task=task
            )
            self.days[day].append(scheduled)
            return scheduled
        else:
            raise ValueError(
                f"Could not find available slot for task in day {day}"
            )

    def schedule_task_to_first_available_slot_in_any_day(
        self, task: "Task"
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
        for day in range(self.num_days):
            try:
                return self.schedule_task_to_first_available_slot_in_day(day, task)
            except ValueError:
                continue  # Try next day
        
        raise ValueError(
            f"Could not schedule task with duration {get_task_duration_minutes(task)} minutes "
            f"in any of the {self.num_days} days"
        )
    
    def schedule_task_to_first_available_slot_balance_days(
        self, task: "Task"
    ) -> ScheduledTask:
        """
        Schedule a task to the first available slot across days, prioritizing
        days with the most available time.
        
        Sorts days by available time in descending order and iteratively tries
        to insert the task into days, starting with those having the most available time.
        
        Args:
            task: Todoist Task object (must have duration set)
            
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

    def get_scheduled_tasks(self) -> List[ScheduledTask]:
        """
        Get a list of all scheduled tasks across all days.
        
        Returns:
            List of ScheduledTask objects that are currently scheduled
        """
        return [task for day in self.days for task in day]
