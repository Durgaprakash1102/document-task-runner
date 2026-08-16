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