from django.db import transaction

from .dependency_service import validate_dependencies
from .models import Task


class WorkflowSubmissionError(Exception):
    pass


@transaction.atomic
def submit_workflow(task_definitions):
    """
    Validate and persist a complete workflow atomically.
    """

    task_names = [
        task_definition["name"]
        for task_definition in task_definitions
    ]

    if len(task_names) != len(set(task_names)):
        raise WorkflowSubmissionError(
            "Task names must be unique within a workflow."
        )

    dependencies = {
        task_definition["name"]: task_definition.get(
            "depends_on",
            [],
        )
        for task_definition in task_definitions
    }

    # Detect cycles and unknown dependencies BEFORE creating tasks.
    validate_dependencies(dependencies)

    tasks_by_name = {}

    for task_definition in task_definitions:
        task = Task.objects.create(
            name=task_definition["name"],
            max_retries=task_definition.get(
                "max_retries",
                3,
            ),
            failure_probability=task_definition.get(
                "failure_probability",
                0.1,
            ),
            min_duration=task_definition.get(
                "min_duration",
                1.0,
            ),
            max_duration=task_definition.get(
                "max_duration",
                3.0,
            ),
        )

        tasks_by_name[task.name] = task

    for task_definition in task_definitions:
        task = tasks_by_name[task_definition["name"]]

        dependency_objects = [
            tasks_by_name[dependency_name]
            for dependency_name in task_definition.get(
                "depends_on",
                [],
            )
        ]

        task.dependencies.set(dependency_objects)

    return list(tasks_by_name.values())