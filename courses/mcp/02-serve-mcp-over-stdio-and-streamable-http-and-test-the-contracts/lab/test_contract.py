"""Contract tests: an in-process client checks the published tools and every call. Run: python -m pytest -v"""
import importlib
import json
from pathlib import Path

import pytest
from jsonschema import validate
from mcp import Client

import contract
import tasks_server

pytestmark = pytest.mark.anyio
PUBLISHED = {tool["name"]: tool for tool in json.loads(contract.CONTRACT.read_text(encoding="utf-8"))}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    server = importlib.reload(tasks_server).server  # a fresh task list for every test
    async with Client(server) as client:
        yield client


async def test_tools_list_matches_the_published_contract(client):
    tools = (await client.list_tools()).tools
    assert [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools] == list(PUBLISHED.values())


@pytest.mark.parametrize("name, arguments", [
    ("list_tasks", {}),
    ("list_tasks", {"status": "done"}),
    ("add_task", {"title": "Tag v1.2", "priority": "high"}),
    ("complete_task", {"task_id": "T-1"}),
])
async def test_each_tool_returns_content_that_matches_its_output_schema(client, name, arguments):
    result = await client.call_tool(name, arguments)
    assert not result.is_error
    validate(result.structured_content, PUBLISHED[name]["outputSchema"])
    assert json.loads(result.content[0].text) == result.structured_content


@pytest.mark.parametrize("name, arguments, message", [
    ("add_task", {"title": "v2"}, "String should have at least 3 characters"),
    ("add_task", {"title": "Tag v1.2", "priority": "urgent"}, "Input should be 'low', 'normal' or 'high'"),
    ("complete_task", {"task_id": "3"}, "String should match pattern"),
    ("complete_task", {"task_id": "T-9"}, "No task with ID T-9. Call list_tasks"),
    ("complete_task", {}, "Field required"),
])
async def test_bad_calls_return_tool_errors(client, name, arguments, message):
    result = await client.call_tool(name, arguments)
    assert result.is_error
    assert message in result.content[0].text
