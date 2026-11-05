# Secrets

docuctl never stores credentials in `ship.toml`. A configuration value that starts with `secret://` is a reference: at deploy time docuctl looks the name up in the secret store of the target environment and passes the value to the service as an environment variable.

Create or replace a secret with:

    docuctl secrets set staging-db-url --env staging

docuctl reads the value from standard input, so it never appears in your shell history. `docuctl secrets list --env staging` shows names and last-change times, never values.

## Rotation

Rotating a secret does not restart the service. After `docuctl secrets set`, run `docuctl restart --env staging` so the running replicas read the new value. A restart replaces replicas one at a time and keeps the current release.

Secrets have no expiry of their own. Deploy tokens do; see the CI page.

## Access

Only engineers with the `secrets:write` role can set a secret, and only for environments their team owns. Reading a secret value is not possible through docuctl at all: the value is decrypted inside the cluster, at process start. If a service needs to check that a secret is present, use `docuctl secrets list`, which reports the names that exist.

## Common mistakes

A typo in a `secret://` name fails the deploy before any replica starts, with the error `unknown secret "staging-db-ulr" in env staging`. A secret that exists in staging but not in production fails only the production deploy, which is why `docuctl deploy --dry-run --env production` is worth running before a first production release.
