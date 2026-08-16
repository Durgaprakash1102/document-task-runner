from django.test import TestCase, TransactionTestCase
from .models import Task, TaskStatus
from unittest.mock import patch
from .runner import TaskRunner
from .dependency_service import (CircularDependencyError,validate_dependencies,)
from .scheduler import TaskScheduler

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