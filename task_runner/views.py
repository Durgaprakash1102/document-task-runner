from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Count, Q

from .models import Task, TaskStatus
from .background import start_scheduler
from .dependency_service import CircularDependencyError
from .models import Task
from .serializers import WorkflowSubmissionSerializer
from .submission_service import (
    WorkflowSubmissionError,
    submit_workflow,
)
from .background import (
    get_scheduler,
    start_scheduler,
)

class WorkflowSubmissionView(APIView):
    def post(self, request):
        serializer = WorkflowSubmissionSerializer(
            data=request.data
        )

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tasks = submit_workflow(
                serializer.validated_data["tasks"]
            )

            start_scheduler()

        except (
            CircularDependencyError,
            ValueError,
            WorkflowSubmissionError,
        ) as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Workflow submitted successfully.",
                "tasks": [
                    {
                        "id": task.id,
                        "name": task.name,
                        "status": task.status,
                    }
                    for task in tasks
                ],
            },
            status=status.HTTP_201_CREATED,
        )


class TaskStatusView(APIView):
    def get(self, request, task_id):
        try:
            task = Task.objects.get(id=task_id)

        except Task.DoesNotExist:
            return Response(
                {
                    "error": "Task not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "attempts": task.attempts,
                "max_retries": task.max_retries,
                "retry_count": task.retry_count,
                "next_retry_at": task.next_retry_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
            status=status.HTTP_200_OK,
        )

class TaskCancellationView(APIView):
    def post(self, request, task_id):
        scheduler = get_scheduler()

        try:
            task = scheduler.cancel_task(task_id)

        except Task.DoesNotExist:
            return Response(
                {
                    "error": "Task not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        except ValueError as exc:
            return Response(
                {
                    "error": str(exc)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Task cancelled successfully.",
                "id": task.id,
                "name": task.name,
                "status": task.status,
            },
            status=status.HTTP_200_OK,
        )

class TaskStatsView(APIView):
    def get(self, request):
        stats = Task.objects.aggregate(
            waiting=Count(
                "id",
                filter=Q(status=TaskStatus.WAITING),
            ),
            running=Count(
                "id",
                filter=Q(status=TaskStatus.RUNNING),
            ),
        )

        return Response(
            {
                "waiting": stats["waiting"],
                "running": stats["running"],
            },
            status=status.HTTP_200_OK,
        )