# Deploy from CI

CI jobs use a deploy token in the `DOCUCTL_TOKEN` environment variable. docuctl reads it automatically, so the job needs no login step. Create the token as the tokens page describes and give it the narrowest scope that works: `deploy:staging` for a job that deploys only to staging.

A typical job runs:

    docuctl deploy --env staging --wait --json

`--wait` makes the command return only when the deploy has finished or failed, and the exit code tells the job which one happened: `0` for a live release, `3` for a failed hook, `4` for a failed health check and `5` for a production deploy that is waiting for approval. `--json` prints a final object with the release name and status.

## Production from CI

A token can have the `deploy:production` scope, but production still needs an approval from a person. The CI job exits with code `5` and the release waits. The approver runs `docuctl approve r42`, and the deploy continues without the CI job.

## Concurrency

Only one deploy per environment can run at a time. A second `docuctl deploy` to the same environment fails at once with `deploy in progress (r42)`. Add `--queue` to wait for the running deploy to finish instead. CI systems that start a job per commit usually want `--queue` for staging and a manual trigger for production.
