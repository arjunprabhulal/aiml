---
title: Troubleshooting
---
# Troubleshooting

## The assistant cites the wrong page

Rebuild the search index with `docs-assistant index --rebuild`.

## The assistant cannot reach Ollama

Check that `OLLAMA_API_BASE` points to a running Ollama server.
