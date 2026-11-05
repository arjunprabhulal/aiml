# Tools in the docs assistant

ADK runs a live agent's tool calls itself and sends each result back to the model.
A tool that returns in under a second can block. A slow tool should be non-blocking or streaming,
so the agent keeps talking while it runs. Call `stop_streaming` to cancel a streaming tool.
