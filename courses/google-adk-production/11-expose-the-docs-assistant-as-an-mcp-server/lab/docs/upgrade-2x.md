# Upgrade from docuctl 1.x to 2.x

docuctl 2.0 renamed several commands and changed two defaults. Commands from 1.x that were removed print an error that names the 2.x replacement.

| docuctl 1.x | docuctl 2.x |
| --- | --- |
| `docuctl release revert <release>` | `docuctl rollback --env <env> --to <release>` |
| `docuctl release list` | `docuctl releases --env <env>` |
| `docuctl push` | `docuctl deploy` |
| `docuctl token new` | `docuctl tokens create` |
| `docuctl tail` | `docuctl logs` |

## Changed defaults

In 1.x, `docuctl deploy` without `--env` deployed to staging. In 2.x it fails and asks for `--env`, so a missing flag can never reach production.

In 1.x, a failing `post_deploy` hook rolled the release back. In 2.x it marks the release `degraded` and keeps it; add `rollback_on_failure = true` to `[hooks]` to keep the 1.x behavior.

## ship.toml

The 1.x `[deploy]` table is now `[service]`. docuctl 2.x still reads `[deploy]` and prints a warning on every command until you rename it. `docuctl config migrate` rewrites the file for you and prints the diff before saving.

## Tokens

Tokens created with 1.x keep working until they expire. They have the `deploy:*` scope, which 2.x no longer creates for new tokens; replace them with tokens scoped to one environment.
