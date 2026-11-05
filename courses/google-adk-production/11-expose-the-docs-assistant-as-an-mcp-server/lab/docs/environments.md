# Environments

An environment is a named target that docuctl deploys to. Every repository starts with two, `staging` and `production`, declared in `ship.toml`:

    [environments.staging]
    cluster = "eu-west-staging"
    replicas = 2

    [environments.production]
    cluster = "eu-west-prod"
    replicas = 6
    approval = true

`cluster` names the compute cluster the release runs on. `replicas` is the number of copies of the service that receive traffic. `approval = true` makes every deploy to that environment wait for `docuctl approve`.

List the environments a repository defines with `docuctl envs`. The output shows each environment's cluster, its current release and the time of its last deploy.

## Preview environments

`docuctl deploy --preview` creates a short-lived environment named after the current Git branch, such as `preview-fix-login`. A preview environment copies its settings from `staging`, runs one replica and is deleted after 72 hours without a deploy. Delete one sooner with `docuctl envs delete preview-fix-login`.

Preview environments never receive production secrets. A `secret://` reference that exists only in production resolves to an empty value in a preview, and docuctl prints a warning that names the secret.

## Environment variables

Variables for one environment go in an `[env.<environment>]` table. Values are plain strings; docuctl does not expand `$VARS` inside them.

    [env.staging]
    LOG_LEVEL = "debug"
    DATABASE_URL = "secret://staging-db-url"

Variables from `[env.default]` apply to every environment, and a value in an environment's own table overrides the default. `docuctl config show --env staging` prints the merged result with secret values masked.
