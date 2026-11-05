---
name: release-notes
description: Write the release notes for a docuctl version from its merged pull requests. Use when someone asks for release notes, a changelog entry or "what changed" in a version.
metadata:
  adk_additional_tools:
    - list_merged_prs
---
Follow these steps exactly.

1. Call `list_merged_prs` with the version the user named.
2. Run `scripts/group_changes.py` with the pull request titles as positional arguments. It groups them by Conventional Commits type and prints JSON.
3. Read `references/style.md` and write the notes in that format, using only the groups the script printed.
4. Never invent a change. If `list_merged_prs` returns an error, report it and stop.
