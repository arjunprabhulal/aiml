# Production deployment approval

Production deployment requires a reviewed release and approval from the on-call maintainer. A maintainer runs `docuctl deploy --env production --release RELEASE_ID --approval APPROVAL_ID`.

If production health checks fail, the maintainer follows the approved rollback runbook and records the release ID in the incident. A reader token cannot retrieve this collection.
