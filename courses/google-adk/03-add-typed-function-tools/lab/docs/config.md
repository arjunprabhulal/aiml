# Configure docuctl

docuctl reads `ship.toml` in the repository root. The `[service]` table names the service and its build command:

    [service]
    name = "docs-api"
    build = "make build"

Environment variables for the service go in `[env.<environment>]` tables. Never put credentials in `ship.toml`; reference a secret with `secret://<name>` instead.
