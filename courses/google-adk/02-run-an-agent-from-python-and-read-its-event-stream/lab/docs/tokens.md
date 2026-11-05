# Authenticate docuctl in CI

CI jobs authenticate with a deploy token, not a personal login. Create one with:

    docuctl tokens create --name ci-docs-api --scope deploy:staging

The token is shown once. Store it in your CI secret store as `DOCUCTL_TOKEN`. Tokens expire after 90 days; `docuctl tokens list` shows each token's expiry.
