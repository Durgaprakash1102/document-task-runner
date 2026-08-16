# Design Decisions

## 1. Overview

Document Task Runner is a small asynchronous task execution service built with Django.

The system accepts a workflow containing multiple tasks and their dependencies, validates the workflow, persists the tasks, and executes eligible tasks asynchronously while respecting dependency and concurrency constraints.

The main execution flow is:

```text
REST API
   ↓
Serializer
   ↓
Workflow Submission Service
   ↓
Dependency Validation
   ↓
Database
   ↓
Background Scheduler
   ↓
Task Runner
   ↓
ThreadPoolExecutor
```

The implementation intentionally focuses on the task-running problem rather than the work performed by each task. Task execution is simulated using a configurable duration and failure probability.

---

# 2. Scenario

The selected scenario is a document-processing workflow.

A realistic workflow can contain tasks such as:

```text
Extract Text
      ↓
Analyze Document
      ↓
Generate Report
```

For example:

- `Extract Text` extracts text from an uploaded document.
- `Analyze Document` performs analysis after extraction succeeds.
- `Generate Report` creates the final report after analysis succeeds.

The actual work is simulated because the assignment explicitly focuses on the runner and scheduler rather than implementing document-processing algorithms.

The task model therefore allows the duration and failure probability to be configured.

---

# 3. Architecture

The system is divided into several responsibilities.

```text
                    REST API
                       │
                       ▼
                  Serializers
                       │
                       ▼
              Submission Service
                       │
                       ▼
            Dependency Validation
                       │
                       ▼
                    SQLite
                       │
                       ▼
             Background Scheduler
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Ready Tasks          Blocked Tasks
             │
             ▼
          TaskRunner
             │
             ▼
     ThreadPoolExecutor
```

## Main components

### `models.py`

Defines the persistent task model and task lifecycle states.

### `dependency_service.py`

Validates submitted dependency graphs and detects circular dependencies.

### `submission_service.py`

Validates and persists complete workflows transactionally.

### `runner.py`

Executes individual tasks and handles execution results, attempts, failures, and retries.

### `scheduler.py`

Determines which tasks are eligible to execute and controls scheduling and concurrency.

### `background.py`

Manages the scheduler's background thread and scheduler lifecycle.

### `views.py`

Provides the REST API endpoints.

### `serializers.py`

Validates incoming API workflow data.

---

# 4. Task Lifecycle

Tasks use the following states:

```text
WAITING
RUNNING
SUCCEEDED
FAILED
BLOCKED
CANCELLED
```

A normal successful execution follows:

```text
WAITING
   ↓
RUNNING
   ↓
SUCCEEDED
```

A task that permanently fails follows:

```text
WAITING
   ↓
RUNNING
   ↓
FAILED
```

A waiting task can be cancelled:

```text
WAITING
   ↓
CANCELLED
```

A task whose dependency permanently fails or is cancelled becomes blocked:

```text
Dependency
    ↓
FAILED / BLOCKED / CANCELLED
    ↓
Dependent Task
    ↓
BLOCKED
```

---

# 5. Dependency Management

A task can depend on one or more other tasks.

For example:

```text
Extract Text
      ↓
Analyze Document
      ↓
Generate Report
```

`Analyze Document` cannot execute until `Extract Text` succeeds.

`Generate Report` cannot execute until `Analyze Document` succeeds.

A task is considered ready only when every dependency has reached:

```text
SUCCEEDED
```

If dependencies are still running or waiting, the task remains waiting.

If any dependency becomes permanently unsuccessful, the dependent task becomes blocked.

---

# 6. Dependency Validation

Dependency validation happens before workflow tasks are persisted.

## Unknown dependencies

A submitted task cannot depend on a task that does not exist in the same workflow.

For example:

```text
Analyze Document → Extract Text
```

is invalid if `Extract Text` was not included in the submission.

The workflow is rejected with a `400 Bad Request`.

## Circular dependencies

Circular dependency graphs are rejected during submission.

Example:

```text
Task A → Task B
Task B → Task C
Task C → Task A
```

The system detects the cycle before execution begins.

This avoids discovering an impossible workflow only after some tasks have already started.

---

# 7. Circular Dependency Detection

Circular dependency detection uses depth-first traversal.

The validation algorithm maintains:

- A set of currently visiting tasks
- A set of already visited tasks
- The current traversal path

If traversal reaches a task already present in the current visiting set, a cycle exists.

For example:

```text
A → B → C → A
```

results in a `CircularDependencyError`.

The workflow is rejected before task persistence.

---

# 8. Transactional Workflow Submission

Workflow submission is handled as a transaction.

The process is:

```text
Receive workflow
      ↓
Validate request
      ↓
Validate dependencies
      ↓
Create tasks
      ↓
Create dependency relationships
      ↓
Commit transaction
```

If validation or persistence fails, the transaction is rolled back.

This prevents partially-created workflows.

For example, if a workflow contains an invalid dependency, the system does not persist only the valid portion of the workflow.

---

# 9. Concurrency Design

The maximum number of concurrently executing tasks is configurable.

The value is loaded from:

```env
TASK_MAX_WORKERS=3
```

The scheduler creates a `ThreadPoolExecutor` using the configured worker count.

For example:

```text
TASK_MAX_WORKERS=3
```

allows:

```text
Task A → RUNNING
Task B → RUNNING
Task C → RUNNING
Task D → WAITING
```

The scheduler tracks submitted futures.

The number of available slots is calculated from:

```text
max_workers - number_of_active_futures
```

A new ready task is submitted only when an available slot exists.

The concurrency setting is not hard-coded to two or three workers. It can be changed through the environment without modifying the scheduling logic.

---

# 10. Required Question 1 — Concurrency Guarantee

## How do you make sure your concurrency limit is never exceeded, even when many tasks are submitted at the same moment?

The scheduler controls task submission rather than submitting every waiting task immediately.

The configured worker limit is passed to `ThreadPoolExecutor`.

The scheduler also tracks its active futures and calculates the number of available worker slots before submitting additional tasks.

Conceptually:

```text
available slots =
    configured workers - currently submitted active futures
```

For example, with:

```text
TASK_MAX_WORKERS=3
```

the scheduler can submit at most three active tasks:

```text
Task A → RUNNING
Task B → RUNNING
Task C → RUNNING
Task D → WAITING
Task E → WAITING
```

When a future completes, it is removed from the scheduler's active-future collection and another ready task can be submitted.

Database state operations are also protected by a shared lock so worker threads do not perform conflicting state updates at the same time.

## What could go wrong if this were incorrect?

If the scheduler ignored the worker limit, a large workflow could start many tasks simultaneously:

```text
Configured limit = 3

Task A → RUNNING
Task B → RUNNING
Task C → RUNNING
Task D → RUNNING
Task E → RUNNING
```

This would violate the core concurrency guarantee and could consume excessive CPU, memory, database connections, or downstream resources.

The concurrency limit therefore has to be enforced by the scheduling mechanism rather than merely reported as a statistic.

---

# 11. Scheduling Policy

When several tasks are ready, the scheduler uses FIFO ordering.

Ready tasks are ordered by:

```text
created_at
id
```

This means the earliest-created ready task is considered first.

Example:

```text
Concurrency limit = 2

Task A → created first
Task B → created second
Task C → created third
```

If all three are ready:

```text
Task A → RUNNING
Task B → RUNNING
Task C → WAITING
```

When one worker becomes available, Task C is considered next.

---

# 12. Required Question 3 — Scheduling Example

## Which task runs next?

The oldest ready task according to creation order runs next.

The policy is FIFO.

## Example where FIFO gives a poor result

Consider:

```text
Concurrency limit = 1

Task A → created first → 30 seconds
Task B → created second → 1 second
Task C → created third → 1 second
```

FIFO executes:

```text
A → B → C
```

Task B and Task C are short but have to wait for the long Task A.

A shortest-job-first policy could reduce average waiting time:

```text
B → C → A
```

However, shortest-job-first would require reliable task duration information and could introduce fairness issues.

FIFO was chosen because it is deterministic, predictable, and simple to reason about.

---

# 13. Retry Strategy

A task can fail according to its configured failure probability.

If retries remain, the task can be retried after an increasing delay.

The retry strategy uses exponential backoff.

Example:

```text
Retry 1 → 1 second
Retry 2 → 2 seconds
Retry 3 → 4 seconds
Retry 4 → 8 seconds
```

The next retry time is stored in:

```text
next_retry_at
```

The task also tracks:

```text
attempts
retry_count
max_retries
```

If the retry limit is exhausted, the task becomes permanently:

```text
FAILED
```

---

# 14. Failure Propagation

If a task permanently fails, its dependent tasks cannot execute.

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

The blocked state can propagate downstream:

```text
A → FAILED
     ↓
B → BLOCKED
     ↓
C → BLOCKED
```

This prevents downstream tasks from waiting indefinitely for a dependency that can never succeed.

---

# 15. Cancellation Decision

The service allows cancellation only for tasks that are still `WAITING`.

The state transition is:

```text
WAITING
   ↓
CANCELLED
```

A `RUNNING` task cannot be forcibly terminated.

## Why?

The task runner uses Python worker threads. Python does not provide a safe general-purpose mechanism for forcibly terminating arbitrary running threads.

Therefore, forcibly killing a running task could leave resources or application state inconsistent.

Instead, cancellation is limited to work that has not started yet.

## What happens to dependent tasks?

If a task is cancelled, a dependent task cannot execute because its dependency did not reach `SUCCEEDED`.

The dependent task therefore becomes:

```text
BLOCKED
```

This is preferable to leaving it permanently in `WAITING`.

---

# 16. Required Question 2 — Restart Behaviour

## What happens when the service is killed while tasks are running?

Task state is persisted in SQLite.

Terminal states survive service restarts:

```text
SUCCEEDED
FAILED
BLOCKED
CANCELLED
```

Tasks that were already `WAITING` remain waiting.

A task persisted as `RUNNING` when the service stops is considered interrupted work.

When a new scheduler starts, it performs recovery:

```text
RUNNING
   ↓
WAITING
```

The scheduler then has the opportunity to execute that task again.

This prevents an interrupted task from remaining permanently stuck in `RUNNING`.

## Can work be lost?

Completed task state is persisted, so completed tasks are not forgotten.

However, work that was in progress when the process terminated may not have its final successful state persisted.

## Can work run twice?

Yes.

For example:

```text
Task starts
    ↓
Actual work completes
    ↓
Process stops before SUCCESS is persisted
    ↓
Service restarts
    ↓
RUNNING → WAITING
    ↓
Task executes again
```

Therefore, the current design does not provide exactly-once execution.

The task workload in this assignment is simulated and has no external side effects, so retrying an interrupted task is acceptable.

For production workloads with external side effects, the system would need mechanisms such as:

- Idempotency keys
- Execution leases
- Durable acknowledgements
- External transaction coordination

The chosen policy prioritizes avoiding permanently stuck tasks while keeping the implementation simple enough for the assignment.

---

# 17. Required Question 4 — Correctness Invariant

The most important correctness invariant is:

> **A task must never execute unless every task it depends on has successfully completed.**

This is enforced by the scheduler's dependency-state check.

A task is `READY` only when all dependencies have:

```text
status == SUCCEEDED
```

If a dependency is:

```text
FAILED
BLOCKED
CANCELLED
```

the dependent task becomes:

```text
BLOCKED
```

If dependencies are still incomplete, the dependent task remains:

```text
WAITING
```

Therefore:

```text
All dependencies succeeded
          ↓
        READY
          ↓
       RUNNING
```

while:

```text
Dependency failed/cancelled
          ↓
       BLOCKED
```

This invariant prevents downstream work from executing before its required prerequisite work has succeeded.

---

# 18. Own Improvement — Retry Observability

The assignment requires task status and the number of attempts.

As an additional operational improvement, the status API exposes more detailed retry information:

```json
{
    "id": 1,
    "name": "Extract Text",
    "status": "WAITING",
    "attempts": 2,
    "max_retries": 3,
    "retry_count": 1,
    "next_retry_at": "2026-08-16T06:00:00Z"
}
```

This allows an operator to determine:

- How many attempts have occurred
- How many retries are configured
- How many retries have already been used
- When the next retry is scheduled

The problem this solves is operational visibility.

Without these fields, an operator would need to inspect application logs to understand why a failed task is still waiting.

This improvement was chosen because it is small but useful when diagnosing asynchronous workflows.

---

# 19. Background Scheduler

The REST API should return without waiting for the complete workflow to finish.

After successful workflow submission:

```text
POST /api/tasks/
       ↓
Validate workflow
       ↓
Persist workflow
       ↓
Start scheduler
       ↓
Return HTTP response
       ↓
Background execution
```

The scheduler is managed by `SchedulerManager`.

The manager is responsible for:

- Starting the scheduler
- Maintaining the scheduler thread
- Preventing duplicate scheduler instances
- Providing access to the active scheduler
- Handling scheduler shutdown

---

# 20. Database and Threading

SQLite is used because it provides simple persistence without requiring a separate database server.

Multiple worker threads can update task state, so critical database state operations are protected using a shared lock.

The implementation avoids holding the database lock during the simulated task execution itself.

The general pattern is:

```text
Acquire lock
    ↓
Read/update task state
    ↓
Release lock
    ↓
Execute simulated task
    ↓
Acquire lock
    ↓
Persist result
    ↓
Release lock
```

This allows workers to execute concurrently while protecting shared database state.

SQLite is suitable for the scope of this assignment, but a production deployment with many concurrent writers would be better served by PostgreSQL.

---

# 21. Task Runner vs. Scheduler

The responsibilities are intentionally separated.

## Scheduler

Responsible for:

- Finding waiting tasks
- Checking dependencies
- Enforcing concurrency
- Applying FIFO ordering
- Managing futures
- Detecting completed tasks
- Handling retries
- Blocking dependent tasks
- Managing cancellation

## Task Runner

Responsible for:

- Executing an individual task
- Updating execution state
- Incrementing attempts
- Simulating execution duration
- Determining success or failure
- Recording retry information

This separation keeps scheduling decisions independent from the actual task execution logic.

---

# 22. API Architecture

The REST API is intentionally thin.

The general architecture is:

```text
API View
   ↓
Serializer
   ↓
Service Layer
   ↓
Database / Scheduler
```

## Workflow submission

```text
WorkflowSubmissionView
        ↓
WorkflowSubmissionSerializer
        ↓
submit_workflow()
        ↓
Dependency Validation
        ↓
Task Persistence
        ↓
start_scheduler()
```

## Task status

```text
TaskStatusView
      ↓
Task
      ↓
JSON Response
```

## Task cancellation

```text
TaskCancellationView
      ↓
Scheduler
      ↓
Cancel Task
      ↓
JSON Response
```

## Statistics

```text
TaskStatsView
      ↓
Database
      ↓
WAITING / RUNNING counts
```

---

# 23. Testing Strategy

The project uses Django's testing framework.

Tests cover the main behavioural requirements.

## Model tests

Verify:

- Task defaults
- Dependency relationships

## Dependency tests

Verify:

- Valid dependency graphs
- Unknown dependencies
- Direct circular dependencies
- Indirect circular dependencies
- Independent tasks

## Runner tests

Verify:

- Successful execution
- Attempt counting
- Failure handling
- Retry behaviour
- Exponential backoff

## Scheduler tests

Verify:

- Tasks without dependencies
- Dependency ordering
- Failed dependency blocking
- Failure propagation
- Concurrency limits
- FIFO scheduling
- Cancellation
- Restart recovery

## API tests

Verify:

- Workflow submission
- Invalid workflow submission
- Task status
- Missing task handling
- Task cancellation
- Statistics

The current test suite contains 27 tests.

---

# 24. Correctness and Failure Handling

The design prioritizes deterministic state transitions.

Important rules include:

```text
WAITING → RUNNING
WAITING → CANCELLED
RUNNING → SUCCEEDED
RUNNING → FAILED
WAITING → BLOCKED
RUNNING → WAITING  (restart recovery)
```

A task should never execute while one of its dependencies is incomplete or unsuccessful.

A dependency that can no longer succeed causes downstream tasks to become blocked rather than waiting forever.

---

# 25. Production Considerations

The current implementation is intentionally lightweight and designed for the assignment.

For a production-scale implementation, possible improvements include:

- PostgreSQL instead of SQLite
- Redis for coordination
- Celery or another distributed task system
- Separate worker processes
- Distributed locking
- Persistent execution leases
- Idempotency keys
- Structured logging
- Metrics and monitoring
- Authentication and authorization
- Workflow-level identifiers
- Better crash recovery semantics

These are outside the scope of the current assignment.

---

# 26. Summary

The design separates:

```text
API
 ↓
Validation
 ↓
Persistence
 ↓
Scheduling
 ↓
Execution
```

The core correctness rule is:

```text
A task executes only after all of its dependencies have succeeded.
```

Concurrency is configurable through the environment, retries use exponential backoff, permanently failed dependencies propagate a blocked state, circular workflows are rejected before persistence, waiting tasks can be cancelled, and interrupted running tasks are recovered after restart.

The implementation deliberately favors a simple, testable architecture suitable for the assignment while documenting the limitations and tradeoffs that would need to be addressed in a production system.