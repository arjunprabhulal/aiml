# Managed ADK sessions and Memory Bank

This lab keeps a local runner and uses regional managed session/memory services. The model client uses its own global endpoint. The 2026-10-25 recording uses the current docuctl manual; its unique instance was deleted after execution.

Install requirements-lock.txt in a Python 3.12+ environment. Offline checks: `python -m unittest -v test_platform.py`.

Cloud reproduction needs an approved project, ADC and permission to create a lesson instance and call the model. Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION for that project. Use GOOGLE_GENAI_USE_ENTERPRISE=true and an environment without a Gemini API key when using ADC. Then run `python create_memory_bank.py`, set AGENT_ENGINE_ID to its printed ID, and run `python record.py`. The recorder refuses pre-existing memories or sessions rather than deleting them. Keep the resource ID and label in your resource inventory. For teardown, `python delete_memory_bank.py YOUR_ENGINE_ID` checks the lesson label before force-deleting the instance, its sessions and memories.

Offline tests mock cloud clients. They check configuration and data-preservation guards, not model accuracy or Memory Bank extraction. The separately rerun managed-topics comparison is in failure-default-topics.txt and failure-default-topics.json. To reproduce that comparison, create a separate instance with `python create_memory_bank.py --managed-topics-only` before running its recorder. The immediate search was empty, and no version memory appeared within the bounded 181-second poll in that run.
