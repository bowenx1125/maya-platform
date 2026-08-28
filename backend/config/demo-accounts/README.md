# Private Demo accounts

The running Demo account catalog is `accounts.private.md`. Copy
`accounts.example.md` to that filename outside Git and replace the example
passwords. The backend reads the Markdown table as a complete desired
identity/membership graph on startup; malformed files fail closed.

Keep the private file readable only by the backend service account:

```sh
chmod 0600 backend/config/demo-accounts/accounts.private.md
```

The catalog is intentionally the only runtime credential source. The older
`backend/config/demo_users.yaml` file is only a one-time migration/rollback
backup for isolated legacy environments and must not be maintained alongside
the private Markdown catalog. If that backup must be used temporarily, set
the server-only `ALLOW_LEGACY_DEMO_USERS=true` switch explicitly and remove it
after migration. Passwords are never returned by the API or written to logs.
`account_key` is an immutable internal key and is not a login field exposed to
browsers; changing a username or removing/re-adding the same key preserves the
platform User UUID.

The surrounding deployment must ignore this directory's private file in both
Git and Docker build context. Do not put real passwords in this example or in
source control.
