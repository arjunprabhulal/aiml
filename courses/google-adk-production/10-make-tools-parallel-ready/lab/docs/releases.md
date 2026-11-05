# Releases

Every successful build becomes a release with a number that increases per repository: `r1`, `r2` and so on. A release is immutable. It records the Git commit, the build output, the `ship.toml` it was built with and the engineer or token that created it. Deploying the same commit twice creates two releases.

`docuctl releases --env production` lists the releases that environment has run, newest first, with a status column:

- `live` is the release that receives traffic now. There is exactly one per environment.
- `previous` releases ran before and can be rolled back to.
- `degraded` releases are live but their `post_deploy` hook failed.
- `failed` releases never received traffic, because a hook or a health check failed.
- `pending` releases are waiting for an approval.

## Inspect a release

`docuctl releases show r42` prints the commit, the author, the build time, the hooks that ran with their exit codes, and the configuration with secret values masked. Add `--diff r41` to compare the configuration of two releases, which is often the fastest way to find why a deploy broke.

## Retention

docuctl keeps the 50 newest releases per environment. Older ones are deleted with their build output, so you cannot roll back to them. `docuctl releases pin r30 --env production` keeps one release beyond that limit, for example the last release before a large migration. `docuctl releases unpin` removes the pin.

## Promote a release

`docuctl promote r42 --from staging --to production` deploys the exact build that runs in staging to production, without rebuilding. The production release gets its own number, records that it was promoted from staging `r42`, and still waits for approval when production requires it. Promotion is the recommended way to release to production, because what reaches production is the build that was tested.
