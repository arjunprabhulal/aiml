# Approvals

An environment with `approval = true` in `ship.toml` holds every deploy until a second engineer approves it. The release waits in the `pending` state, and its replicas are not started.

    docuctl approve r42

The approver must have the `deploy:production` role and must not be the engineer who started the deploy; docuctl rejects a self-approval with `approver must differ from deployer`. A CI token can start a deploy but can never approve one.

`docuctl pending --env production` lists the releases that wait for an approval, with who started each one and when. A pending release expires after 24 hours and is marked `failed`, so a forgotten deploy cannot go out days later.

## Reject a deploy

`docuctl reject r42 --reason "migration not reviewed"` stops a pending release. The reason is stored in `docuctl events`, and the engineer who started the deploy sees it in the output of `docuctl deploy --wait`.

## Emergency changes

There is no flag that skips an approval. For an urgent fix, the fastest path is `docuctl rollback`, which does not need an approval because it returns to a release that was already approved. A rollback to a release older than seven days does need one, because its configuration may no longer match the environment.
