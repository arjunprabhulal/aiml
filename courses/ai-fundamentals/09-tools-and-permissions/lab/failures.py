"""Where tool calling goes wrong. Run: python failures.py"""
import json

import ollama
from ollama._utils import convert_function_to_tool

from docs_tools import TOOLS, answer, definition, read_page, run_tool

# 1. Passing the Python function lets the client build the schema, and the Literal enum is lost.
generated = convert_function_to_tool(read_page).function.parameters.properties["page"]
print("1. client-generated page schema:", generated.model_dump_json(exclude_none=True))
print("   Pydantic page schema:        ", json.dumps(definition(read_page)["function"]["parameters"]["properties"]["page"]))
for line in answer(ollama.Client(), "Open the secrets.md page and tell me what it says.", tools=list(TOOLS.values())):
    print("1.", line)

# 2. The user names a page that does not exist. With the enum the model substitutes a valid page;
#    a call that does reach the application with a bad value becomes an error result, not an exception.
for line in answer(ollama.Client(), "Open the secrets.md page and tell me what it says."):
    print("2.", line)
print("2.", run_tool("read_page", {"page": "secrets.md"})[:120])

# 3. A tool name the application never offered is refused, not executed.
print("3.", run_tool("delete_page", {"page": "rollback.md"}))

# 4. A round limit stops a model that keeps calling tools.
for line in answer(ollama.Client(), "How do I roll back production to r41?", max_rounds=1):
    print("4.", line)
