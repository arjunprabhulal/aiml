# Rollback a staging release

To undo a staging deployment in docuctl 3.5, list known releases with `docuctl releases --env staging`. Then run `docuctl rollback --env staging --to RELEASE_ID`.

After rollback, run `docuctl status --env staging` and check that the active release matches RELEASE_ID. The assistant explains these commands; it does not execute them.
