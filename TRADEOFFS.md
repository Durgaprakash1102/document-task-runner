# Engineering Tradeoffs

This project was intentionally kept small and self-contained so that the core task scheduling behaviour is easy to understand, test, and run from a clean clone.

The following decisions were made where multiple reasonable approaches were possible.

---

## 1. ThreadPoolExecutor vs. Celery

### Chosen approach

The task runner uses Python's `ThreadPoolExecutor`.

### Alternative considered

A distributed task queue such as Celery with Redis or RabbitMQ.

### Why ThreadPoolExecutor was chosen

The assignment requires concurrent task execution but does not require distributed workers or multiple application instances.

`ThreadPoolExecutor` provides:

- Configurable worker count
- Concurrent task execution
- Future-based completion tracking
- No external message broker
- Simple local setup
- Straightforward testing

This keeps the implementation focused on the scheduling problem rather than introducing infrastructure that is not required for the assignment.

### Downside

The scheduler is tied to the application process.

If the system needed multiple worker machines, durable queues, or horizontal scaling, a distributed task queue would be more appropriate.

---

## 2. SQLite vs. PostgreSQL

### Chosen approach

The project uses SQLite for persistence.

### Alternative considered

PostgreSQL.

### Why SQLite was chosen

SQLite requires no separate database server.

This allows someone to clone the repository and run the application by following the README without installing or configuring another service.

It also keeps the project focused on the task runner instead of database deployment.

### Downside

SQLite has more limited concurrent-write behaviour than PostgreSQL.

Because multiple worker threads can update task state, the implementation needs synchronization around critical database operations.

For a production service with many concurrent workers or multiple application instances, PostgreSQL would be a better choice.

---

## 3. FIFO Scheduling vs. Priority / Shortest-Job-First

### Chosen approach

The scheduler uses FIFO ordering for ready tasks.

Tasks are ordered by creation time and then ID.

### Alternative considered

Priority scheduling or shortest-job-first scheduling.

### Why FIFO was chosen

FIFO provides:

- Deterministic behaviour
- Predictable scheduling
- Fairness based on arrival order
- Simple implementation
- Easy testing

It also avoids requiring clients to provide another scheduling priority.

### Downside

FIFO can produce poor results when a long task arrives before several short tasks.

For example:

```text
Concurrency limit = 1

Task A → created first → 30 seconds
Task B → created second → 1 second
Task C → created third → 1 second
```

FIFO produces:

```text
Task A
   ↓
Task B
   ↓
Task C
```

The two short tasks wait for the 30-second task.

A shortest-job-first strategy could produce:

```text
Task B
   ↓
Task C
   ↓
Task A
```

and reduce average waiting time.

However, shortest-job-first would require reliable duration information and could cause long tasks to be repeatedly delayed by shorter tasks.

FIFO was therefore chosen for its simplicity, fairness, and predictability.

---

## 4. Background Scheduler vs. Separate Worker Process

### Chosen approach

The service starts the scheduler in a background thread after a workflow is submitted.

### Alternative considered

Running the scheduler as a separate worker process or using an external task queue.

### Why the background scheduler was chosen

The assignment asks for a small service and does not require a separate worker deployment.

A background scheduler provides:

- Asynchronous execution
- Immediate API responses
- Simple deployment
- No additional worker service
- Easy local development

This keeps the architecture small enough to understand within the scope of the assignment.

### Downside

The scheduler's in-memory execution state belongs to the application process.

If the process stops unexpectedly, active in-memory futures are lost.

The database therefore remains the source of truth for persisted task state, and the implementation explicitly recovers tasks that were persisted as `RUNNING` when a new scheduler starts.

A production implementation would likely use a durable task queue and separate worker processes.

---

# Summary of Tradeoffs

| Decision | Chosen | Alternative | Main Reason |
|---|---|---|---|
| Task execution | ThreadPoolExecutor | Celery + broker | Simpler and sufficient for the assignment |
| Database | SQLite | PostgreSQL | Zero external setup |
| Scheduling | FIFO | Priority / shortest-job-first | Deterministic and fair |
| Background execution | Application thread | Separate workers | Smaller deployment footprint |

These decisions prioritize simplicity, transparency, and ease of testing while acknowledging the limitations that would need to be addressed in a production-scale implementation.