# Database migrations

docuctl does not know what a migration is. It runs whatever command you put in the `pre_deploy` hook, and most teams put their migration tool there:

    [hooks]
    pre_deploy = "alembic upgrade head"

Because `pre_deploy` runs before the new release receives traffic, the old release is still serving while the migration runs. Every migration must therefore work with both the old and the new code: add a column before the code that writes it, and drop a column only after no deployed release reads it.

## Rollbacks and migrations

`docuctl rollback` moves traffic to an earlier release. It does not run any hook, so it does not undo a migration. If the release you are leaving added a column, the column stays. If it removed one, the earlier release may fail when it reads that column.

The safe order for a schema change that has to be undone is:

1. Write a new migration that reverses the change.
2. Deploy it as a new release.
3. Only then roll back the application, if you still need to.

## Long migrations

A migration that takes longer than the hook time limit fails the deploy. Raise `hook_timeout`, or run the slow part as a background job outside the deploy. Never run a long table rewrite in `pre_deploy` on a large production table without testing it on a copy of the data first; it holds the deploy, and on some databases it holds a lock.
