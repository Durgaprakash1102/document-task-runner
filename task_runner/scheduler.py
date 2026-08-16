import time
from threading import RLock

from django.db import close_old_connections, models
from django.utils import timezone

from .models import Task, TaskStatus
from .runner import TaskRunner


class TaskScheduler:
    def __init__(self, max_workers=3, poll_interval=0.05):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")

        self.max_workers = max_workers
        self.poll_interval = poll_interval

        # Shared lock for database state operations.
        self.db_lock = RLock()

        self.runner = TaskRunner(
            max_workers=max_workers,
            db_lock=self.db_lock,
        )

        self.futures = {}

    def shutdown(self):
        self.runner.shutdown()

    def _get_waiting_tasks(self):
        with self.db_lock:
            return list(
                Task.objects.filter(
                    status=TaskStatus.WAITING
                )
                .filter(
                    models.Q(next_retry_at__isnull=True)
                    | models.Q(
                        next_retry_at__lte=timezone.now()
                    )
                )
                .order_by("created_at", "id")
            )

    def _dependency_state(self, task):
        with self.db_lock:
            dependencies = list(
                task.dependencies.all()
            )

            if not dependencies:
                return "READY"

            if any(
                dependency.status in {
                    TaskStatus.FAILED,
                    TaskStatus.BLOCKED,
                    TaskStatus.CANCELLED,
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
        with self.db_lock:
            task.status = TaskStatus.BLOCKED

            task.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

    def _submit_ready_tasks(self):
        available_slots = (
            self.max_workers - len(self.futures)
        )

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
        completed = [
            future
            for future in self.futures
            if future.done()
        ]

        for future in completed:
            self.futures.pop(future)

            future.result()

    def run_until_idle(self):
        close_old_connections()

        try:
            while True:
                self._collect_completed_tasks()
                self._submit_ready_tasks()
                self._collect_completed_tasks()

                with self.db_lock:
                    waiting_tasks = list(
                        Task.objects.filter(
                            status=TaskStatus.WAITING
                        ).order_by("created_at", "id")
                    )

                # Nothing is running and nothing is waiting.
                if not self.futures and not waiting_tasks:
                    break

                # Tasks are waiting, but they may be waiting for
                # a retry time or for dependencies.
                if not self.futures and waiting_tasks:
                    with self.db_lock:
                        ready_tasks_exist = Task.objects.filter(
                            status=TaskStatus.WAITING
                        ).filter(
                            models.Q(next_retry_at__isnull=True)
                            | models.Q(
                                next_retry_at__lte=timezone.now()
                            )
                        ).exists()

                    if ready_tasks_exist:
                        continue

                    # No task is currently runnable.
                    # Wait briefly and check again.
                    time.sleep(self.poll_interval)
                    continue

                time.sleep(self.poll_interval)

        finally:
            close_old_connections()

    def cancel_task(self, task_id):
        with self.db_lock:
            task = Task.objects.get(id=task_id)

            if task.status != TaskStatus.WAITING:
                raise ValueError(
                    "Only WAITING tasks can be cancelled."
                )

            task.status = TaskStatus.CANCELLED
            task.next_retry_at = None

            task.save(
                update_fields=[
                    "status",
                    "next_retry_at",
                    "updated_at",
                ]
            )

        return task