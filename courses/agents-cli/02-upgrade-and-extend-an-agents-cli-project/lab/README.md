# Enhance, upgrade, and extend an Agents CLI project

This is the complete `agents-cli-upgrade-extend` teaching lab. Extract it and begin in this directory. Install Python 3.12+ and uv before running the commands below.

Keep the generated project from Lesson 1. Replace `/absolute/path/to/docuctl-docs` with its real path. The extracted lab and generated project are different directories.

## Commands, in lesson order

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
LAB_DIR="$PWD"
```

```bash
export PROJECT_DIR="/absolute/path/to/docuctl-docs"
cd "$PROJECT_DIR"
```

```bash
agents-cli scaffold enhance . \
  --deployment-target cloud_run \
  --cicd-runner github_actions \
  --bq-analytics \
  --region us-central1 \
  -y
```

```bash
# Preview the 3-way merge without touching disk
agents-cli scaffold upgrade . --dry-run

# Preview force mode when you want fresh template scaffolding
agents-cli scaffold upgrade . --force --dry-run
```

```bash
cp "$LAB_DIR/agents-cli-extension.yaml" "$PROJECT_DIR/agents-cli-extension.yaml"
```

```bash
# Inspect active project and user extensions
agents-cli info

# Run the newly added release-check command
agents-cli release-check

# Run the replacement test command (this does not deploy)
agents-cli deploy -q
```

```bash
cd "$LAB_DIR"
"$LAB_DIR/.venv/bin/python" -m unittest -v test_upgrade_extend.py
```

## What the checks establish

Offline tests exercise local helpers and supplied examples. They do not invoke Gemini, deploy infrastructure, register an agent or verify telemetry delivery. Model-generation commands can incur charges; deployment and registration require your own cloud resources and credentials.


The sample extension replaces `deploy` with pytest. It does not deploy after the tests finish. Terraform and telemetry snippets in later labs are excerpts; provision using the complete generated project.

The saved commands actually enhanced the project and ran the extension. Both upgrade previews used CLI 1.11.0 against a 1.11.0 project and correctly reported no update; merge classifications are separate local unit cases.
