from django.test import TestCase

from .models import Task, TaskStatus


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

from .dependency_service import (CircularDependencyError,validate_dependencies,)

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