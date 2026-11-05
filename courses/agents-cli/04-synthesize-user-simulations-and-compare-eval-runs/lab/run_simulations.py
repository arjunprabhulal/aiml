"""Run saved generated scenarios against the agent with explicit model limits.

Uses the same ADK inference generator as agents-cli 1.11.0. Scenario generation
is a separate CLI activity; this script never calls the scenario service.
"""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys

from google.adk.evaluation.conversation_scenarios import ConversationScenario
from google.adk.evaluation.eval_case import SessionInput
from google.adk.evaluation.evaluation_generator import EvaluationGenerator
from google.adk.evaluation.simulation.llm_backed_user_simulator import (
    LlmBackedUserSimulator, LlmBackedUserSimulatorConfig,
)
from google.genai import types


def public_value(value):
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items()
                if key not in {"thoughtSignature", "thought_signature"}}
    if isinstance(value, list):
        return [public_value(item) for item in value]
    return value


async def run(project, scenarios, output):
    sys.path.insert(0, str(project.resolve()))
    agent = importlib.import_module("app.agent").root_agent
    data = json.loads(scenarios.read_text())
    if len(data["eval_cases"]) != 3:
        raise ValueError("This bounded exercise requires exactly three scenarios")
    results = []
    for case in data["eval_cases"]:
        simulator = LlmBackedUserSimulator(
            conversation_scenario=ConversationScenario(**case["user_scenario"]),
            config=LlmBackedUserSimulatorConfig(
                max_allowed_invocations=4,
                model="gemini-3.8-flash",
                model_configuration=types.GenerateContentConfig(
                    max_output_tokens=2048,
                    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
                ),
            ),
        )
        invocations = await EvaluationGenerator._generate_inferences_from_root_agent(
            root_agent=agent, user_simulator=simulator, reset_func=None,
            initial_session=SessionInput(app_name="docuctl_simulation", user_id="learner", state={}),
        )
        results.append({
            "eval_case_id": case["eval_case_id"],
            "user_scenario": case["user_scenario"],
            "turns_generated": len(invocations),
            "invocations": public_value([item.model_dump(mode="json", exclude_none=True) for item in invocations]),
        })
        print(f"{case['eval_case_id']}: {len(invocations)} actual turns", flush=True)
    output.write_text(json.dumps({"execution_mode": "actual-ADK-user-simulation", "model": "gemini-3.8-flash", "max_turns": 4, "eval_cases": results}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.project, args.scenarios, args.output))
