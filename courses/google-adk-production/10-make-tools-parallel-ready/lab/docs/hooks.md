# Deploy hooks

A hook is a command that docuctl runs at a fixed point of a deploy. Hooks are declared in `ship.toml`:

    [hooks]
    pre_deploy = "make migrate"
    post_deploy = "make smoke-test"

`pre_deploy` runs once, in a one-off container built from the new release, before any replica receives traffic. A non-zero exit code stops the deploy and the environment keeps its current release. This is where database migrations usually run.

`post_deploy` runs after every replica of the new release passes its health check. A failing `post_deploy` hook does not roll the release back on its own; it marks the release as `degraded` in `docuctl releases`. Add `rollback_on_failure = true` to the `[hooks]` table to make docuctl roll back automatically when `post_deploy` fails.

Each hook has a time limit of 15 minutes. Change it with `hook_timeout = "30m"`. A hook that runs out of time is treated as a failure.

## Hook environment

Hooks receive the same environment variables and secrets as the service, plus `SHIP_RELEASE` (the new release, such as `r42`), `SHIP_PREVIOUS_RELEASE` and `SHIP_ENV`. Hooks cannot ask for input; anything that reads standard input receives end-of-file.

## Logs

Hook output is stored with the release. `docuctl logs --release r42 --hook pre_deploy` prints it. When a deploy stops in a hook, docuctl prints the last 20 lines of the hook output and the command to see the rest.
