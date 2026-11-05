# Health checks

A replica receives traffic only after it passes its health check. docuctl sends `GET /healthz` to each new replica every 5 seconds and waits for three successful responses in a row. Change the path and timing in `ship.toml`:

    [health]
    path = "/ready"
    interval = "10s"
    healthy_after = 3
    timeout = "5m"

If no replica of the new release passes within `timeout`, the deploy fails and the environment keeps the release it had. The failed replicas are stopped, and `docuctl events` shows `health check failed` with the last response code.

## What a health check should test

The endpoint should answer when the process can serve requests: the server is listening and its required dependencies, such as the database, are reachable. It should not call other services that have their own deploys, because then one service's outage fails every other service's deploy.

## After the deploy

Health checks keep running while the release is live. A replica that fails three checks in a row is restarted, and the restart appears in `docuctl events`. If all replicas keep failing, the environment is marked `unhealthy`, but docuctl does not roll back on its own. Run `docuctl rollback --env production` to move traffic to the previous release.
