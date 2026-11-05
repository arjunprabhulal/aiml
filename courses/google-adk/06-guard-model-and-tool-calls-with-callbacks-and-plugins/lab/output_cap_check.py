"""Inspect real GenAI SDK serialization with a local mock transport, never inference."""
import asyncio
import json
from unittest.mock import patch
import httpx
from google import genai
from google.genai import types
from google.adk.models import Gemini


def assert_capped_wire(test, requests):
    """Send real ADK LlmRequests through Gemini/GenAI into an in-process transport."""
    async def go():
        sent = []
        def fake(request):
            test.assertEqual(request.method, "POST")
            test.assertEqual(str(request.url),
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"index": 0,
                "finishReason": "STOP", "content": {"role": "model", "parts": [
                    {"text": "OFFLINE_SERIALIZATION_FIXTURE_NOT_MODEL_OUTPUT"}]}}]})
        def deny_sync(request):
            raise AssertionError("Unexpected sync provider transport")
        client = genai.Client(api_key="offline-placeholder", enterprise=False, vertexai=False,
            http_options=types.HttpOptions(
                httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(fake), trust_env=False),
                httpx_client=httpx.Client(transport=httpx.MockTransport(deny_sync), trust_env=False),
                retry_options=types.HttpRetryOptions(attempts=1)))
        try:
            with patch.object(Gemini, "api_client", property(lambda self: client)):
                model = Gemini(model="gemini-3.8-flash")
                for request in requests:
                    async for _ in model.generate_content_async(request, stream=False):
                        pass
            test.assertEqual(len(sent), len(requests))
            for body in sent:
                test.assertEqual(body["generationConfig"]["maxOutputTokens"], 1024)
            return sent
        finally:
            await client.aio.aclose()
            client.close()
    return asyncio.run(go())
