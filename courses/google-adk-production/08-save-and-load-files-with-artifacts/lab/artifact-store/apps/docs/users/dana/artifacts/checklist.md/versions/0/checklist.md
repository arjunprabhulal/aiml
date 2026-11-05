# Production Deploy Checklist

1. **Verify Secrets**: Ensure no plaintext credentials exist in `ship.toml` and all sensitive values use `secret://<name>`.
2. **Confirm Secret Availability**: Run `docuctl secrets list --env production` to confirm all referenced secrets exist in production.
3. **Enable Approvals**: Ensure `approval = true` is set under `[environments.production]` in `ship.toml`.
4. **Run Dry Run**: Execute `docuctl deploy --dry-run --env production` to validate configuration and secret references without deploying.
5. **Review Merged Config**: Run `docuctl config show --env production` to verify resolved variables and settings before starting the deploy.
