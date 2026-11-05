# Rotate an API token

To rotate an API token in docuctl 3.5, create a replacement with `docuctl token create --name rotation`. Update the application's secret store and check a request before revoking the old token with `docuctl token revoke TOKEN_ID`.

Never put an API token in documentation, a shell history or a support message. These instructions use TOKEN_ID as a placeholder, not a credential.
