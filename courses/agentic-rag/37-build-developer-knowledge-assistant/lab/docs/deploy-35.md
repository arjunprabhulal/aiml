# Staging deployment

To deploy a staging release with docuctl 3.5, run `docuctl deploy --env staging --release RELEASE_ID`. Confirm the release with `docuctl status --env staging`.

The deploy command waits for the rollout. A failed health check stops the rollout; inspect `docuctl logs --env staging` before trying another release.
