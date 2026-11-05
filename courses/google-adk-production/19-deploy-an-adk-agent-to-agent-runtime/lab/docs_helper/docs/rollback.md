# Roll back a release

`docuctl rollback` moves an environment back to an earlier release. It does not rebuild anything; it points traffic at the release you name.

    docuctl rollback --env production --to r41

Without `--to`, docuctl rolls back to the previous release. A rollback is itself recorded as a new release, so `docuctl releases` shows it.

Database migrations are not rolled back. If the release you leave ran a migration, write a new migration that reverses it.

docuctl 1.x used `docuctl release revert <release>`. That command was removed in docuctl 2.0.
