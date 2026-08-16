# Document Task Runner

A small Django-based asynchronous task runner for dependency-aware document-processing workflows.

The service accepts a workflow containing tasks and dependencies, executes ready tasks concurrently, retries failures with exponential backoff, blocks tasks whose dependencies permanently fail, and persists task state in SQLite.

## Scenario

The project models a document-processing workflow such as:

```text
Extract Text
      ↓
Analyze Document
      ↓
Generate Report
```

Each task simulates work using a configurable duration and failure probability.

## Features

- Dependency-aware task execution
- Circular dependency detection
- Configurable concurrency limit
- FIFO scheduling
- Configurable retries with exponential backoff
- Failed-dependency propagation
- Task cancellation
- Restart recovery for interrupted tasks
- REST API for workflow submission and task status
- Running/waiting task statistics
- Retry-state visibility
- SQLite persistence
- Automated tests

## Tech Stack

- Python
- Django
- Django REST Framework
- SQLite
- ThreadPoolExecutor
- python-dotenv

## Project Structure

```text
document-task-runner/
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── task_runner/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── views.py
│   ├── scheduler.py
│   ├── runner.py
│   ├── dependency_service.py
│   ├── submission_service.py
│   ├── background.py
│   ├── serializers.py
│   └── tests.py
│
├── .env.example
├── .gitignore
├── DESIGN.md
├── TRADEOFFS.md
├── manage.py
├── requirements.txt
└── README.md
```

# Setup

## 1. Clone the repository

```bash
git clone https://github.com/Durgaprakash1102/document-task-runner.git
cd document-task-runner
```

## 2. Create a virtual environment

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
```

### Linux/macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure environment variables

Create a `.env` file in the project root.

Use `.env.example` as the template:

```env
TASK_MAX_WORKERS=3
```

`TASK_MAX_WORKERS` controls the maximum number of tasks that can execute concurrently.

For example:

```env
TASK_MAX_WORKERS=1
```

allows one task to run at a time.

```env
TASK_MAX_WORKERS=5
```

allows up to five tasks to run concurrently.

The `.env` file is intentionally excluded from Git.

## 5. Apply migrations

```bash
python manage.py migrate
```

## 6. Run the tests

```bash
python manage.py test
```

The current test suite contains 27 tests.

## 7. Start the development server

```bash
python manage.py runserver
```

The API will be available at:

```text
http://127.0.0.1:8000/
```

# API

## 1. Submit a Workflow

### Endpoint

```http
POST /api/tasks/
```

### Example Request

```json
{
    "tasks": [
        {
            "name": "Extract Text",
            "failure_probability": 0,
            "max_retries": 3,
            "min_duration": 1,
            "max_duration": 2
        },
        {
            "name": "Analyze Document",
            "depends_on": ["Extract Text"],
            "failure_probability": 0,
            "max_retries": 2,
            "min_duration": 1,
            "max_duration": 2
        },
        {
            "name": "Generate Report",
            "depends_on": ["Analyze Document"],
            "failure_probability": 0,
            "max_retries": 1,
            "min_duration": 1,
            "max_duration": 2
        }
    ]
}
```

### Example Response

```json
{
    "message": "Workflow submitted successfully.",
    "tasks": [
        {
            "id": 1,
            "name": "Extract Text",
            "status": "WAITING"
        },
        {
            "id": 2,
            "name": "Analyze Document",
            "status": "WAITING"
        },
        {
            "id": 3,
            "name": "Generate Report",
            "status": "WAITING"
        }
    ]
}
```

The workflow is executed asynchronously after submission.

---

## 2. Get Task Status

### Endpoint

```http
GET /api/tasks/<id>/
```

### Example

```http
GET /api/tasks/1/
```

### Example Response

```json
{
    "id": 1,
    "name": "Extract Text",
    "status": "SUCCEEDED",
    "attempts": 1,
    "max_retries": 3,
    "retry_count": 0,
    "next_retry_at": null,
    "created_at": "2026-08-16T05:23:47.650082Z",
    "updated_at": "2026-08-16T05:23:49.650082Z"
}
```

Possible task states are:

```text
WAITING
RUNNING
SUCCEEDED
FAILED
BLOCKED
CANCELLED
```

The additional retry fields make retry progress visible without requiring access to application logs.

---

## 3. Cancel a Task

### Endpoint

```http
POST /api/tasks/<id>/cancel/
```

### Example

```http
POST /api/tasks/5/cancel/
```

### Example Response

```json
{
    "message": "Task cancelled successfully.",
    "id": 5,
    "name": "Waiting Task",
    "status": "CANCELLED"
}
```

Only tasks in the `WAITING` state can be cancelled.

A task that is already `RUNNING` cannot be forcibly terminated.

Dependent tasks are prevented from running because a cancelled dependency did not successfully complete.

---

## 4. Get Task Statistics

### Endpoint

```http
GET /api/stats/
```

### Example Response

```json
{
    "waiting": 1,
    "running": 2
}
```

The endpoint reports the number of tasks currently in the `WAITING` and `RUNNING` states.

# Task Execution

A task executes only after all of its dependencies have successfully completed.

For example:

```text
Extract Text
      ↓
Analyze Document
      ↓
Generate Report
```

The execution order is:

```text
Extract Text
      ↓
SUCCEEDED
      ↓
Analyze Document
      ↓
SUCCEEDED
      ↓
Generate Report
      ↓
SUCCEEDED
```

If a task has no dependencies, it is eligible to run immediately.

# Concurrency

The concurrency limit is configured through:

```env
TASK_MAX_WORKERS=3
```

If the limit is `3`:

```text
Task A → RUNNING
Task B → RUNNING
Task C → RUNNING
Task D → WAITING
Task E → WAITING
```

When one running task completes, the next eligible waiting task can be scheduled.

The scheduler uses `ThreadPoolExecutor` with the configured worker count and tracks submitted futures so that it never intentionally schedules more than the configured number of active tasks.

Ready tasks are selected using FIFO ordering based on creation time.

# Retry and Backoff

Tasks can fail according to their configured failure probability.

Failed tasks can be retried until their configured retry limit is reached.

Retry delays use exponential backoff:

```text
Retry 1 → 1 second
Retry 2 → 2 seconds
Retry 3 → 4 seconds
Retry 4 → 8 seconds
```

The next retry time is persisted in the database.

If the maximum retry limit is exhausted, the task becomes:

```text
FAILED
```

# Failure Propagation

If a task permanently fails, dependent tasks become blocked.

For example:

```text
Extract Text
      ↓
FAILED
      ↓
Analyze Document
      ↓
BLOCKED
```

The blocked state propagates to downstream tasks:

```text
A → FAILED
     ↓
B → BLOCKED
     ↓
C → BLOCKED
```

Blocked tasks are never executed.

# Circular Dependencies

Circular dependencies are detected during workflow submission.

For example:

```text
Task A → Task B
Task B → Task C
Task C → Task A
```

The workflow is rejected with a clear error before tasks are persisted.

Unknown dependencies are also rejected.

# Cancellation

Only `WAITING` tasks can be cancelled:

```text
WAITING
   ↓
CANCELLED
```

Running tasks are not forcibly terminated because Python does not provide a safe general-purpose mechanism for killing arbitrary running threads.

A cancelled dependency causes dependent tasks to become blocked rather than allowing them to execute without a successful prerequisite.

# Restart Recovery

Task state is persisted in SQLite.

Terminal states survive service restarts:

```text
SUCCEEDED
FAILED
BLOCKED
CANCELLED
```

Tasks that were `WAITING` remain waiting.

If a task was persisted as `RUNNING` when the service stopped, the next scheduler startup treats it as interrupted work and changes it back to:

```text
WAITING
```

The task can then be executed again.

This prevents a task from remaining permanently stuck in the `RUNNING` state.

A task may execute twice if its actual work completed immediately before the process stopped but its successful state was not persisted. The current task workload is simulated and has no external side effects. A production system performing external operations would require idempotency or execution leases to prevent duplicate side effects.

# Testing

Run:

```bash
python manage.py test
```

The test suite currently contains 27 tests covering:

- Task model defaults
- Task dependencies
- Dependency validation
- Unknown dependencies
- Direct circular dependencies
- Indirect circular dependencies
- Independent tasks
- Successful execution
- Retry behaviour
- Failure propagation
- Dependency blocking
- Concurrency limits
- FIFO scheduling
- Task cancellation
- Restart recovery
- Workflow submission API
- Task status API
- Task cancellation API
- Statistics API
- Invalid API requests

# Documentation

Additional engineering decisions are documented in:

```text
DESIGN.md
```

Tradeoffs between alternative implementation approaches are documented in:

```text
TRADEOFFS.md
```

# Repository

GitHub:

https://github.com/Durgaprakash1102/document-task-runner