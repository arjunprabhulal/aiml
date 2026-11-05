"""The terminal entrypoint releases its Runner after a failed invocation."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import agent

class RunnerLifecycle(unittest.TestCase):
    def test_failed_turn_closes_the_runner(self):
        runner = SimpleNamespace(close=AsyncMock())
        with patch.object(agent, "Runner", return_value=runner), patch.object(
            agent, "ask", new=AsyncMock(side_effect=RuntimeError("failed turn"))
        ):
            with self.assertRaisesRegex(RuntimeError, "failed turn"):
                asyncio.run(agent.main("Inspect the docs"))
        runner.close.assert_awaited_once()
