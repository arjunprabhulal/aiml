"""An MCP server for a project task tracker, with typed tool contracts. Run over stdio: python tasks_server.py"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

Status = Literal["open", "done"]
Priority = Literal["low", "normal", "high"]
TaskId = Annotated[str, Field(pattern=r"^T-\d+$", description="A task ID such as T-1, as returned by list_tasks.")]


class Task(BaseModel):
    """One task in the tracker."""
    id: str = Field(description="Task ID such as T-1.")
    title: str
    priority: Priority
    status: Status


class TaskList(BaseModel):
    """The tasks that match a filter."""
    tasks: list[Task]
    count: int


server = MCPServer("tasks", version="1.0.0", instructions="Read and update the task tracker of one software project.")

TASKS: dict[str, Task] = {task.id: task for task in [
    Task(id="T-1", title="Write the release notes", priority="normal", status="open"),
    Task(id="T-2", title="Fix the login redirect bug", priority="high", status="done"),
    Task(id="T-3", title="Update the API docs", priority="low", status="open"),
]}


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def list_tasks(status: Status | None = None) -> TaskList:
    """List the project's tasks. Pass status to return only open or only done tasks."""
    tasks = [task for task in TASKS.values() if status is None or task.status == status]
    return TaskList(tasks=tasks, count=len(tasks))


@server.tool()
def add_task(title: Annotated[str, Field(min_length=3, max_length=80)], priority: Priority = "normal") -> Task:
    """Add an open task and return it with its new ID."""
    task = Task(id=f"T-{len(TASKS) + 1}", title=title, priority=priority, status="open")
    TASKS[task.id] = task
    return task


@server.tool(annotations=ToolAnnotations(idempotent_hint=True))
def complete_task(task_id: TaskId) -> Task:
    """Mark one task as done and return it."""
    if task_id not in TASKS:
        raise ToolError(f"No task with ID {task_id}. Call list_tasks to see the valid IDs.")
    TASKS[task_id].status = "done"
    return TASKS[task_id]


if __name__ == "__main__":
    server.run()
