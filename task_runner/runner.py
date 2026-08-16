import random
import time
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections

from .models import Task, TaskStatus


class TaskRunner:
    def __init__(self, max_workers=3):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")

        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers
        )

    def shutdown(self):
        self.executor.shutdown(wait=True)

    def run_task(self, task_id):
        close_old_connections()

        try:
            task = Task.objects.get(id=task_id)

            task.status = TaskStatus.RUNNING
            task.attempts += 1
            task.save(
                update_fields=[
                    "status",
                    "attempts",
                    "updated_at",
                ]
            )

            try:
                duration = random.uniform(
                    task.min_duration,
                    task.max_duration,
                )

                time.sleep(duration)

                if random.random() < task.failure_probability:
                    raise RuntimeError("Simulated task failure")

                task.status = TaskStatus.SUCCEEDED
                task.save(
                    update_fields=["status", "updated_at"]
                )

            except Exception:
                if task.attempts <= task.max_retries:
                    task.status = TaskStatus.WAITING
                else:
                    task.status = TaskStatus.FAILED

                task.save(
                    update_fields=["status", "updated_at"]
                )

        finally:
            close_old_connections()