# docuctl: a fictional deployment CLI

Deploy the service in the current directory to staging:

    docuctl deploy --env staging

List staging releases, newest first:

    docuctl releases --env staging

Roll production back to release r41 without rebuilding it:

    docuctl rollback --env production --to r41

A rollback changes the application release. It does not reverse database migrations.
