class CircularDependencyError(Exception):
    pass


def validate_dependencies(task_dependencies):
    task_names = set(task_dependencies.keys())

    # Every dependency must refer to a task in the same submission.
    for task_name, dependencies in task_dependencies.items():
        for dependency in dependencies:
            if dependency not in task_names:
                raise ValueError(
                    f"Task '{task_name}' depends on unknown task "
                    f"'{dependency}'."
                )

    visiting = set()
    visited = set()

    def visit(task_name, path):
        if task_name in visiting:
            cycle_start = path.index(task_name)
            cycle = path[cycle_start:] + [task_name]

            raise CircularDependencyError(
                "Circular dependency detected: "
                + " -> ".join(cycle)
            )

        if task_name in visited:
            return

        visiting.add(task_name)

        for dependency in task_dependencies[task_name]:
            visit(dependency, path + [task_name])

        visiting.remove(task_name)
        visited.add(task_name)

    for task_name in task_names:
        visit(task_name, [])

    return True