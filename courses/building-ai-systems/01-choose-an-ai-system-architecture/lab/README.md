# Choose an architecture from task requirements

Python 3.12+, standard library only. No API key, model download or GPU.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python architecture.py
python -m unittest -v test_architecture.py
```

The program returns a versioned command template or a maintainer action proposal. It never executes docuctl. pages.json contains fictional source documents; cases.json supplies the requests.

run-output.txt contains the saved local output. run-metadata.json binds the source, tests, input files and output by SHA-256.
