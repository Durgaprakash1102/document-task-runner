import threading

from .scheduler import TaskScheduler


class SchedulerManager:
    def __init__(self, max_workers=3):
        self.max_workers = max_workers
        self.scheduler = None
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return self.scheduler

            self.scheduler = TaskScheduler(
                max_workers=self.max_workers,
                poll_interval=0.05,
            )

            self.thread = threading.Thread(
                target=self._run,
                args=(self.scheduler,),
                daemon=True,
                name="task-runner-scheduler",
            )

            self.thread.start()

            return self.scheduler

    def _run(self, scheduler):
        try:
            scheduler.run_until_idle()

        except Exception as exc:
            print(
                f"Scheduler error: {exc}"
            )

        finally:
            # The scheduler thread owns the executor lifecycle.
            scheduler.shutdown()

            with self.lock:
                if self.scheduler is scheduler:
                    self.scheduler = None

                if self.thread is threading.current_thread():
                    self.thread = None

    def get_scheduler(self):
        with self.lock:
            return self.scheduler

    def stop(self):
        """
        Wait for the scheduler thread to finish.

        The scheduler thread itself is responsible for calling
        scheduler.shutdown() after run_until_idle() completes.
        """
        with self.lock:
            thread = self.thread

        if (
            thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join()

        with self.lock:
            self.scheduler = None
            self.thread = None


from django.conf import settings


scheduler_manager = SchedulerManager(
    max_workers=settings.TASK_MAX_WORKERS
)


def start_scheduler():
    return scheduler_manager.start()


def get_scheduler():
    scheduler = scheduler_manager.get_scheduler()

    if scheduler is None:
        scheduler = scheduler_manager.start()

    return scheduler