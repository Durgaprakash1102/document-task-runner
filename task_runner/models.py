from django.db import models


class TaskStatus(models.TextChoices):
    WAITING = "WAITING", "Waiting"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    BLOCKED = "BLOCKED", "Blocked"
    CANCELLED = "CANCELLED", "Cancelled"

class Task(models.Model):
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=20,choices=TaskStatus.choices,default=TaskStatus.WAITING,)
    attempts = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True,blank=True,)
    max_retries = models.PositiveIntegerField(default=3)
    failure_probability = models.FloatField(default=0.1)
    min_duration = models.FloatField(default=1.0)
    max_duration = models.FloatField(default=3.0)
    dependencies = models.ManyToManyField("self",symmetrical=False,blank=True,related_name="dependents",)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.status})"