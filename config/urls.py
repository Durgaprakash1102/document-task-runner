from django.contrib import admin
from django.urls import path

from task_runner.views import *


urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "api/tasks/",
        WorkflowSubmissionView.as_view(),
        name="task-submit",
    ),
    path(
    "api/tasks/<int:task_id>/",
    TaskStatusView.as_view(),
    name="task-status",
    ),
    path(
    "api/tasks/<int:task_id>/cancel/",
    TaskCancellationView.as_view(),
    name="task-cancel",
    ),
    path(
    "api/stats/",
    TaskStatsView.as_view(),
    name="task-stats",
),
]