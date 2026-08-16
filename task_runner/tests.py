from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .dependency_service import (
    CircularDependencyError,
    validate_dependencies,
)
from .models import Task, TaskStatus
from .runner import TaskRunner
from .scheduler import TaskScheduler
from rest_framework.test import APIClient

class TaskModelTests(TestCase):
    def test_task_defaults(self):
        task = Task.objects.create(name="Extract Text",)
        self.assertEqual(task.status, TaskStatus.WAITING)
        self.assertEqual(task.attempts, 0)
        self.assertEqual(task.max_retries, 3)
        self.assertEqual(task.failure_probability, 0.1)
        self.assertEqual(task.min_duration, 1.0)
        self.assertEqual(task.max_duration, 3.0)

    def test_task_can_have_dependencies(self):
        extract_text = Task.objects.create(name="Extract Text",)
        analyze_document = Task.objects.create(name="Analyze Document",)
        analyze_document.dependencies.add(extract_text)
        self.assertIn(extract_text,analyze_document.dependencies.all(),)
        self.assertIn(analyze_document,extract_text.dependents.all(),)

class DependencyValidationTests(TestCase):

    def test_valid_dependency_graph_is_accepted(self):
        dependencies = {
            "extract_text": [],
            "analyze_document": ["extract_text"],
            "generate_report": ["analyze_document"],
        }

        self.assertTrue(validate_dependencies(dependencies))

    def test_unknown_dependency_is_rejected(self):
        dependencies = {
            "analyze_document": ["extract_text"],
        }

        with self.assertRaises(ValueError):
            validate_dependencies(dependencies)

    def test_direct_circular_dependency_is_rejected(self):
        dependencies = {
            "task_a": ["task_b"],
            "task_b": ["task_a"],
        }

        with self.assertRaises(CircularDependencyError):
            validate_dependencies(dependencies)

    def test_indirect_circular_dependency_is_rejected(self):
        dependencies = {
            "task_a": ["task_b"],
            "task_b": ["task_c"],
            "task_c": ["task_a"],
        }

        with self.assertRaises(CircularDependencyError):
            validate_dependencies(dependencies)

    def test_multiple_independent_tasks_are_valid(self):
        dependencies = {
            "extract_text": [],
            "generate_preview": [],
            "send_notification": [],
        }

        self.assertTrue(validate_dependencies(dependencies))

class TaskRunnerTests(TestCase):

    @patch("task_runner.runner.time.sleep")
    @patch("task_runner.runner.random.random", return_value=0.9)
    @patch("task_runner.runner.random.uniform", return_value=0)
    def test_successful_task_execution(
        self,
        mock_uniform,
        mock_random,
        mock_sleep,
    ):
        task = Task.objects.create(
            name="Extract Text",
            failure_probability=0.1,
        )

        runner = TaskRunner(max_workers=2)

        try:
            runner.run_task(task.id)

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.SUCCEEDED,
            )

            self.assertEqual(
                task.attempts,
                1,
            )

        finally:
            runner.shutdown()

    @patch("task_runner.runner.time.sleep")
    @patch("task_runner.runner.random.random", return_value=0.0)
    @patch("task_runner.runner.random.uniform", return_value=0)
    def test_failed_task_is_scheduled_for_retry(
        self,
        mock_uniform,
        mock_random,
        mock_sleep,
    ):
        task = Task.objects.create(
            name="Extract Text",
            failure_probability=1.0,
            max_retries=3,
            min_duration=0,
            max_duration=0,
        )

        runner = TaskRunner(max_workers=1)

        try:
            runner.run_task(task.id)

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.WAITING,
            )

            self.assertEqual(
                task.attempts,
                1,
            )

            self.assertEqual(
                task.retry_count,
                1,
            )

            self.assertIsNotNone(
                task.next_retry_at,
            )

        finally:
            runner.shutdown()
    
    @patch("task_runner.runner.time.sleep")
    @patch("task_runner.runner.random.random", return_value=0.0)
    @patch("task_runner.runner.random.uniform", return_value=0)
    def test_retry_delay_increases_exponentially(
        self,
        mock_uniform,
        mock_random,
        mock_sleep,
    ):
        task = Task.objects.create(
            name="Generate Report",
            failure_probability=1.0,
            max_retries=3,
            min_duration=0,
            max_duration=0,
        )

        runner = TaskRunner(max_workers=1)

        try:
            first_delay = runner._calculate_retry_delay(1)
            second_delay = runner._calculate_retry_delay(2)
            third_delay = runner._calculate_retry_delay(3)

            self.assertEqual(first_delay, 1)
            self.assertEqual(second_delay, 2)
            self.assertEqual(third_delay, 4)

        finally:
            runner.shutdown()
    
    @patch("task_runner.runner.time.sleep")
    @patch("task_runner.runner.random.random", return_value=0.0)
    @patch("task_runner.runner.random.uniform", return_value=0)
    def test_task_permanently_fails_after_retries(
        self,
        mock_uniform,
        mock_random,
        mock_sleep,
    ):
        task = Task.objects.create(
            name="Generate Report",
            failure_probability=1.0,
            max_retries=0,
            min_duration=0,
            max_duration=0,
        )

        runner = TaskRunner(max_workers=1)

        try:
            runner.run_task(task.id)

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.FAILED,
            )

            self.assertEqual(
                task.attempts,
                1,
            )

        finally:
            runner.shutdown()

class TaskSchedulerTests(TransactionTestCase):

    def test_task_with_no_dependencies_runs(self):
        task = Task.objects.create(
            name="Extract Text",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        scheduler = TaskScheduler(
            max_workers=2,
            poll_interval=0.001,
        )

        try:
            scheduler.run_until_idle()

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.SUCCEEDED,
            )

            self.assertEqual(
                task.attempts,
                1,
            )

        finally:
            scheduler.shutdown()

    def test_dependent_task_waits_for_dependency(self):
        extract_text = Task.objects.create(
            name="Extract Text",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        analyze_document = Task.objects.create(
            name="Analyze Document",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        analyze_document.dependencies.add(extract_text)

        scheduler = TaskScheduler(
            max_workers=2,
            poll_interval=0.001,
        )

        try:
            scheduler.run_until_idle()

            extract_text.refresh_from_db()
            analyze_document.refresh_from_db()

            self.assertEqual(
                extract_text.status,
                TaskStatus.SUCCEEDED,
            )

            self.assertEqual(
                analyze_document.status,
                TaskStatus.SUCCEEDED,
            )

            self.assertEqual(
                extract_text.attempts,
                1,
            )

            self.assertEqual(
                analyze_document.attempts,
                1,
            )

        finally:
            scheduler.shutdown()

    def test_failed_dependency_blocks_dependent_task(self):
        extract_text = Task.objects.create(
            name="Extract Text",
            min_duration=0,
            max_duration=0,
            failure_probability=1,
            max_retries=0,
        )

        analyze_document = Task.objects.create(
            name="Analyze Document",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        analyze_document.dependencies.add(extract_text)

        scheduler = TaskScheduler(
            max_workers=2,
            poll_interval=0.001,
        )

        try:
            scheduler.run_until_idle()

            extract_text.refresh_from_db()
            analyze_document.refresh_from_db()

            self.assertEqual(
                extract_text.status,
                TaskStatus.FAILED,
            )

            self.assertEqual(
                analyze_document.status,
                TaskStatus.BLOCKED,
            )

            self.assertEqual(
                analyze_document.attempts,
                0,
            )

        finally:
            scheduler.shutdown()
    
    def test_concurrency_never_exceeds_limit(self):
        tasks = [
            Task.objects.create(
                name=f"Task {index}",
                min_duration=0,
                max_duration=0,
                failure_probability=0,
            )
            for index in range(6)
        ]

        scheduler = TaskScheduler(
            max_workers=2,
            poll_interval=0.001,
        )

        try:
            submitted_tasks = []

            def fake_submit(task_function, task_id):
                submitted_tasks.append(task_id)

                from concurrent.futures import Future

                future = Future()
                scheduler.futures[future] = task_id

                return future

            scheduler.runner.executor.submit = fake_submit

            scheduler._submit_ready_tasks()

            self.assertEqual(
                len(submitted_tasks),
                2,
            )

            self.assertEqual(
                len(scheduler.futures),
                2,
            )

        finally:
            scheduler.shutdown()

    def test_failure_blocks_entire_downstream_chain(self):
        extract_text = Task.objects.create(
            name="Extract Text",
            min_duration=0,
            max_duration=0,
            failure_probability=1,
            max_retries=0,
        )

        analyze_document = Task.objects.create(
            name="Analyze Document",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        generate_report = Task.objects.create(
            name="Generate Report",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        analyze_document.dependencies.add(extract_text)
        generate_report.dependencies.add(analyze_document)

        scheduler = TaskScheduler(
            max_workers=2,
            poll_interval=0.001,
        )

        try:
            scheduler.run_until_idle()

            extract_text.refresh_from_db()
            analyze_document.refresh_from_db()
            generate_report.refresh_from_db()

            self.assertEqual(
                extract_text.status,
                TaskStatus.FAILED,
            )

            self.assertEqual(
                analyze_document.status,
                TaskStatus.BLOCKED,
            )

            self.assertEqual(
                generate_report.status,
                TaskStatus.BLOCKED,
            )

            self.assertEqual(
                analyze_document.attempts,
                0,
            )

            self.assertEqual(
                generate_report.attempts,
                0,
            )

        finally:
            scheduler.shutdown()

    def test_retry_is_not_run_before_retry_time(self):
        task = Task.objects.create(
            name="Extract Text",
            status=TaskStatus.WAITING,
            retry_count=1,
            next_retry_at=timezone.now() + timedelta(seconds=60),
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        scheduler = TaskScheduler(
            max_workers=1,
            poll_interval=0.001,
        )

        try:
            scheduler._submit_ready_tasks()

            self.assertEqual(
                len(scheduler.futures),
                0,
            )

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.WAITING,
            )

        finally:
            scheduler.shutdown()

    def test_waiting_task_can_be_cancelled(self):
        task = Task.objects.create(
            name="Generate Report",
            status=TaskStatus.WAITING,
        )

        scheduler = TaskScheduler(
            max_workers=1,
            poll_interval=0.001,
        )

        try:
            scheduler.cancel_task(task.id)

            task.refresh_from_db()

            self.assertEqual(
                task.status,
                TaskStatus.CANCELLED,
            )

        finally:
            scheduler.shutdown()

    def test_running_task_cannot_be_cancelled(self):
        task = Task.objects.create(
            name="Generate Report",
            status=TaskStatus.RUNNING,
        )

        scheduler = TaskScheduler(
            max_workers=1,
            poll_interval=0.001,
        )

        try:
            with self.assertRaises(ValueError):
                scheduler.cancel_task(task.id)

        finally:
            scheduler.shutdown()

    def test_cancelled_dependency_blocks_dependent_task(self):
        source = Task.objects.create(
            name="Extract Text",
            status=TaskStatus.WAITING,
        )

        dependent = Task.objects.create(
            name="Analyze Document",
            status=TaskStatus.WAITING,
        )

        dependent.dependencies.add(source)

        scheduler = TaskScheduler(
            max_workers=1,
            poll_interval=0.001,
        )

        try:
            scheduler.cancel_task(source.id)

            scheduler._submit_ready_tasks()

            source.refresh_from_db()
            dependent.refresh_from_db()

            self.assertEqual(
                source.status,
                TaskStatus.CANCELLED,
            )

            self.assertEqual(
                dependent.status,
                TaskStatus.BLOCKED,
            )

        finally:
            scheduler.shutdown()

    def test_ready_tasks_are_scheduled_in_fifo_order(self):
        first_task = Task.objects.create(
            name="First Task",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        second_task = Task.objects.create(
            name="Second Task",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        third_task = Task.objects.create(
            name="Third Task",
            min_duration=0,
            max_duration=0,
            failure_probability=0,
        )

        scheduler = TaskScheduler(
            max_workers=1,
            poll_interval=0.001,
        )

        submitted_tasks = []

        def fake_submit(task_function, task_id):
            from concurrent.futures import Future

            submitted_tasks.append(task_id)

            future = Future()
            scheduler.futures[future] = task_id

            return future

        scheduler.runner.executor.submit = fake_submit

        try:
            scheduler._submit_ready_tasks()

            self.assertEqual(
                submitted_tasks,
                [first_task.id],
            )

        finally:
            scheduler.futures.clear()
            scheduler.shutdown()

class TaskAPITests(TransactionTestCase):

    def setUp(self):
        self.client = APIClient()
    
    def tearDown(self):
        from .background import scheduler_manager

        scheduler_manager.stop()
        super().tearDown()
        
    def test_submit_workflow(self):
        response = self.client.post(
            "/api/tasks/",
            {
                "tasks": [
                    {
                        "name": "Extract Text",
                        "failure_probability": 0,
                        "min_duration": 0,
                        "max_duration": 0,
                    },
                    {
                        "name": "Analyze Document",
                        "depends_on": ["Extract Text"],
                        "failure_probability": 0,
                        "min_duration": 0,
                        "max_duration": 0,
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertEqual(
            len(response.data["tasks"]),
            2,
        )

    def test_get_task_status(self):
        task = Task.objects.create(
            name="Extract Text",
        )

        response = self.client.get(
            f"/api/tasks/{task.id}/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data["id"],
            task.id,
        )

    def test_cancel_waiting_task(self):
        task = Task.objects.create(
            name="Long Task",
            status=TaskStatus.WAITING,
        )

        response = self.client.post(
            f"/api/tasks/{task.id}/cancel/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        task.refresh_from_db()

        self.assertEqual(
            task.status,
            TaskStatus.CANCELLED,
        )

    def test_stats_endpoint(self):
        Task.objects.create(
            name="Waiting Task",
            status=TaskStatus.WAITING,
        )

        Task.objects.create(
            name="Running Task",
            status=TaskStatus.RUNNING,
        )

        Task.objects.create(
            name="Succeeded Task",
            status=TaskStatus.SUCCEEDED,
        )

        response = self.client.get(
            "/api/stats/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.data["waiting"],
            1,
        )

        self.assertEqual(
            response.data["running"],
            1,
        )

    def test_circular_dependency_is_rejected(self):
        response = self.client.post(
            "/api/tasks/",
            {
                "tasks": [
                    {
                        "name": "Task A",
                        "depends_on": ["Task C"],
                    },
                    {
                        "name": "Task B",
                        "depends_on": ["Task A"],
                    },
                    {
                        "name": "Task C",
                        "depends_on": ["Task B"],
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertIn(
            "error",
            response.data,
        )

        self.assertEqual(
            Task.objects.count(),
            0,
        )