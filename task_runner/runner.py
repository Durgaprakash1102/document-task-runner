import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import RLock

from django.db import close_old_connections
from django.utils import timezone

from .models import Task, TaskStatus


class TaskRunner:
    def __init__(self, max_workers=3, db_lock=None):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")

        self.max_workers = max_workers
        self.db_lock = db_lock or RLock()

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers
        )

    def shutdown(self):
        self.executor.shutdown(wait=True)

    def _calculate_retry_delay(self, retry_count):
        """
        Exponential backoff:
        retry 1 -> 1 second
        retry 2 -> 2 seconds
        retry 3 -> 4 seconds
        """
        return 2 ** (retry_count - 1)

    def run_task(self, task_id):
        close_old_connections()

        try:
            # Database read + state transition.
            with self.db_lock:
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

                min_duration = task.min_duration
                max_duration = task.max_duration
                failure_probability = task.failure_probability
                max_retries = task.max_retries

            # IMPORTANT:
            # The actual task work happens OUTSIDE the database lock.
            duration = random.uniform(
                min_duration,
                max_duration,
            )

            time.sleep(duration)

            if random.random() < failure_probability:
                raise RuntimeError("Simulated task failure")

            # Successful state transition.
            with self.db_lock:
                task = Task.objects.get(id=task_id)

                task.status = TaskStatus.SUCCEEDED
                task.next_retry_at = None

                task.save(
                    update_fields=[
                        "status",
                        "next_retry_at",
                        "updated_at",
                    ]
                )

        except Exception:
            with self.db_lock:
                task = Task.objects.get(id=task_id)

                if task.attempts <= max_retries:
                    task.status = TaskStatus.WAITING
                    task.retry_count += 1

                    delay = self._calculate_retry_delay(
                        task.retry_count
                    )

                    task.next_retry_at = (
                        timezone.now()
                        + timedelta(seconds=delay)
                    )

                    task.save(
                        update_fields=[
                            "status",
                            "retry_count",
                            "next_retry_at",
                            "updated_at",
                        ]
                    )

                else:
                    task.status = TaskStatus.FAILED
                    task.next_retry_at = None

                    task.save(
                        update_fields=[
                            "status",
                            "next_retry_at",
                            "updated_at",
                        ]
                    )

        finally:
            close_old_connections()