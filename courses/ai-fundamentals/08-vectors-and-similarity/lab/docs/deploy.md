# Deploy a service with docuctl

`docuctl deploy` builds the service in the current directory and releases it to one environment.

    docuctl deploy --env staging

Every deploy creates a numbered release, such as `r42`. `docuctl releases --env staging` lists them, newest first.

Production deploys need an approval: `docuctl deploy --env production` waits until a second engineer runs `docuctl approve <release>`.
