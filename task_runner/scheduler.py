import time
from concurrent.futures import Future

from django.db import close_old_connections

from .models import Task, TaskStatus
from .runner import TaskRunner


class TaskScheduler:
    def __init__(self, max_workers=3, poll_interval=0.05):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")

        self.max_workers = max_workers
        self.poll_interval = poll_interval
        self.runner = TaskRunner(max_workers=max_workers)

        self.futures = {}

    def shutdown(self):
        self.runner.shutdown()

    def _get_waiting_tasks(self):
        """
        Return waiting tasks in FIFO order.

        created_at determines the submission order.
        id is used as a deterministic tie-breaker.
        """
        return list(
            Task.objects.filter(
                status=TaskStatus.WAITING
            ).order_by("created_at", "id")
        )

    def _dependency_state(self, task):
        """
        Determine whether a task is ready, blocked, or waiting.

        Returns:
            "READY"
            "BLOCKED"
            "WAITING"
        """

        dependencies = list(task.dependencies.all())

        if not dependencies:
            return "READY"

        if any(
            dependency.status in {
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
            }
            for dependency in dependencies
        ):
            return "BLOCKED"

        if all(
            dependency.status == TaskStatus.SUCCEEDED
            for dependency in dependencies
        ):
            return "READY"

        return "WAITING"

    def _block_task(self, task):
        task.status = TaskStatus.BLOCKED
        task.save(update_fields=["status", "updated_at"])

    def _submit_ready_tasks(self):
        """
        Submit as many ready tasks as possible without exceeding
        the configured concurrency limit.
        """

        available_slots = self.max_workers - len(self.futures)

        if available_slots <= 0:
            return

        waiting_tasks = self._get_waiting_tasks()

        for task in waiting_tasks:
            if available_slots <= 0:
                break

            state = self._dependency_state(task)

            if state == "BLOCKED":
                self._block_task(task)
                continue

            if state != "READY":
                continue

            future = self.runner.executor.submit(
                self.runner.run_task,
                task.id,
            )

            self.futures[future] = task.id
            available_slots -= 1

    def _collect_completed_tasks(self):
        """
        Remove completed futures from the active set.
        """

        completed = [
            future
            for future in self.futures
            if future.done()
        ]

        for future in completed:
            task_id = self.futures.pop(future)

            # Re-raise unexpected worker exceptions rather than
            # silently hiding them.
            future.result()

    def run_until_idle(self):
        """
        Run tasks until there is no active or runnable work left.
        """

        close_old_connections()

        try:
            while True:
                self._collect_completed_tasks()

                self._submit_ready_tasks()

                self._collect_completed_tasks()

                waiting_exists = Task.objects.filter(
                    status=TaskStatus.WAITING
                ).exists()

                if not self.futures and not waiting_exists:
                    break

                if not self.futures and waiting_exists:
                    # Waiting tasks should either eventually become
                    # ready or become blocked. If neither is possible,
                    # something is inconsistent in the dependency graph.
                    self._submit_ready_tasks()

                    waiting_exists = Task.objects.filter(
                        status=TaskStatus.WAITING
                    ).exists()

                    if waiting_exists and not self.futures:
                        raise RuntimeError(
                            "Scheduler detected tasks that cannot "
                            "make progress."
                        )

                time.sleep(self.poll_interval)

        finally:
            close_old_connections()