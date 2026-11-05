# Review of `ship.toml`

The following issues were identified prior to deploying to production:

- **Line 8**: Hardcoded secret in `DATABASE_URL = "postgres://app:secretpass@db.internal:5432/app"`.  
  **Fix**: Store credentials securely using `docuctl secrets set` and reference them with a secret URI: `DATABASE_URL = "secret://prod-db-url"`.
- **Line 9**: Plaintext secret in `API_KEY = "prod_live_9f83a2c01"`.  
  **Fix**: Store the key in the secret store and reference it: `API_KEY = "secret://prod-api-key"`.
- **Line 14**: Missing production deployment safeguards in `[environments.production]`.  
  **Fix**: Add `approval = true` under `[environments.production]` to require manual approval for production deploys.
