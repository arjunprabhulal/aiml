# Troubleshooting

Start with `docuctl events --env <env>`, which shows the last step that changed the environment. Then read the logs of that step.

## The deploy stops in pre_deploy

The hook exited with a non-zero code. Read the full output with `docuctl logs --release <release> --hook pre_deploy`. The environment kept its previous release, so nothing is broken for users. Fix the hook command or the migration, then deploy again.

## health check failed

No replica answered the health check within the timeout. Read the replica logs with `docuctl logs --release <release> --since 15m`. The usual causes are a missing environment variable, a wrong port, or a dependency that the health endpoint calls and that is down. The `--json` output of `docuctl events` includes the last HTTP status the check received.

## unknown secret

The deploy references a `secret://` name that does not exist in that environment. Check the spelling with `docuctl secrets list --env <env>` and create it with `docuctl secrets set`.

## deploy in progress

Another deploy to the same environment is running. Wait for it, or rerun with `--queue`.

## token expired

Deploy tokens expire after 90 days. Create a new token, update `DOCUCTL_TOKEN` in the CI secret store, and delete the old token with `docuctl tokens delete <name>`.

## The service is slow after a deploy

docuctl does not measure latency. Compare the release's logs with the previous one, and roll back with `docuctl rollback --env <env>` while you investigate; the rollback keeps the database as it is.
