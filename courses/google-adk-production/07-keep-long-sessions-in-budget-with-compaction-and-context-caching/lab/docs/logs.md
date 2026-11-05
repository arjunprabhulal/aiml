# Read logs

`docuctl logs` prints the output of a running service. Without options it follows the newest release in `staging` and prints new lines as they arrive:

    docuctl logs --env staging

Useful options:

- `--release r42` reads the logs of one release instead of the newest.
- `--since 30m` starts 30 minutes ago instead of at the end. It accepts `s`, `m`, `h` and `d`.
- `--replica 3` reads one replica. Replicas are numbered from 1.
- `--grep "timeout"` keeps only lines that contain the text.
- `--hook pre_deploy` reads the output of a deploy hook instead of the service.
- `--no-follow` prints what exists and exits, which suits scripts.

Logs are kept for 14 days in staging and 30 days in production. Older lines are gone; export them to your own store if you need them longer.

## Deploy events

`docuctl events --env production` lists what happened to an environment: deploys, approvals, rollbacks, restarts and failed health checks, each with the engineer or token that caused it. Every event carries the release it belongs to. When a deploy fails, the events show the step that failed before the logs do, so start there.

## Structured output

Every `docuctl` command that prints a table accepts `--json`. `docuctl logs --json` prints one JSON object per line with `time`, `replica`, `release` and `line` fields, which is easier to filter with `jq` than plain text.
