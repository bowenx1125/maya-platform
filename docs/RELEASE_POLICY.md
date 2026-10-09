# Release and Runtime Handoff Policy

## Development source

The canonical private development branch contains source, tests, migrations, lockfiles,
OpenAPI/WebSocket contracts, non-secret Gate evidence and CI. Every release points to a
specific passing development SHA.

## Runtime artifacts

Runtime handoffs are generated from the passing SHA as Docker images or a GitHub Release
artifact. They do not replace the development branch with a new unrelated root commit.
The artifact may omit tests and historical evidence, but its manifest must record the
source SHA and generation command.

## Excluded material

`.env`, account passwords, API keys, student audio, runtime `data/`, databases, logs,
caches, local backups and private reference repositories are excluded from source and
runtime artifacts. Repository/secret-boundary checks are mandatory before publication.

## Historical runtime snapshot

The pre-Wave-4 runtime-only commit `2fd80784bd79c88261eb2319a961b5c659b9e687`
is retained under `runtime-handoff-20260830`. It is recovery evidence, not the current
development authority.

## Release Gate

Before producing a runtime artifact:

1. the exact source SHA passes deterministic CI and the active Gate;
2. generated contracts are clean;
3. secret/repository boundaries pass;
4. Docker images build from frozen locks;
5. the artifact manifest records source SHA, included paths and checksums;
6. the main window verifies the artifact without private runtime inputs.

## Public website acceptance

The production profile must use an exact HTTPS origin, protected individual account
credentials and no Demo identity selection, switching or automatic Demo consent.
Local HTTP/Demo manual acceptance remains a separate deployment configuration.
The Demo profile stays on a private network and must not be exposed. Open
self-enrollment into the configured course/group remains the explicit product
policy; it must not be described as invitation-only enrollment.

Public-release checks include exact-origin authentication and mutations, recoverable
authentication abuse protection, private response cache policy, secure cookies,
TLS/redirect/security headers, QR links, SSE/WebSocket recovery, and all existing
resource/Tool/privacy boundaries. Authentication safeguards do not limit ordinary
Chat, Tool calls, authored content, Provider usage or cost. A readable error must
state an actual retry time or next step without a new workflow panel.

UI acceptance follows the current Final UI Polish Spec and user decisions: the
colleague's warm-paper Home, the same Studyform/Brainform structure for both roles,
central sidebar actions, immediate help, stable glass navigation text, shared RAG
operations and the text-only Chatform. Verify desktop/mobile screenshots, keyboard,
loading/empty/error recovery and identity changes. A test count alone cannot establish
visual quality or prove a real user journey.

The final teaching journey uses dedicated synthetic data: four Agents, an actual
Teacher Agent generation Tool call, one shared canonical Knowledge, multiple distinct
students with Public/Private attempts, actual saved answers/evaluation/Boundary, and a
Teacher Agent's scoped statistics/report/download. Real Provider receipts and privacy
exclusion are separate from Fake tests and infrastructure load measurements.

Backups include a consistent SQLite snapshot plus its referenced files, protected
configuration and compatible source/image identity. Verify file receipts, DB integrity,
foreign keys, migration preservation and a separate-instance restore; never force an
unsafe downgrade. Record measured recovery and HTTP capacity, and keep configured
public DNS/TLS, off-host backup retention and operator monitoring distinct from local
verification. No public hostname, external backup destination or third-party monitoring
service is provisioned implicitly by this policy.

## Initial public server

This stage has no product usage ceiling. Chat, Tools, authored text, debate
rounds, student registration, Provider calls and fees are not rejected because
of count, tokens, CNY, words or elapsed use. Legacy `max_*` fields stay
accounting estimates. Explicit retry authorization and unknown-acceptance
recovery stay separate from budgeting. Authentication failure windows and the
login/register body limit stay; they are abuse controls, not usage quotas.
ACL, CSRF, SSRF, idempotency, privacy and the provider ledger stay as they are.

The production profile is the only public deployment, and it uses the reviewed
public HTTPS origin. The base Compose file is the private Demo: gateway port
8080 and a private-LAN `CLASSROOM_PUBLIC_BASE_URL` that includes that port. Do
not publish the Demo, do not point public DNS at it, and do not reuse its data
directory, account catalog or password for the public site.

The owner set these on October 9, 2026. Recording them is not a claim that
the public site is serving or that a certificate has been issued.

- **Domain.** `MAYA_DOMAIN=app.mayaform.net`. DNS A for `app` was observed at
  `8.210.57.144`.
- **TLS.** No certificate or private key is in git. Caddy requests one for
  `MAYA_DOMAIN` after the production stack starts and `ACME_EMAIL` is set.
  Certificate state stays in the `maya_caddy_data` volume. That request has
  not been made yet.
- **Server.** `8.210.57.144`, Ubuntu 24.04, Docker Engine and Compose
  installed, public TCP 80 and 443 intended for this project only. Do not
  run the command below against an existing local classroom, including a
  `maya-production` project already published on port 8090.
- **Public base URL.** The production override sets
  `CLASSROOM_PUBLIC_BASE_URL` to `https://app.mayaform.net` and omits a port.
  The origin check treats `:443` as the same origin as an omitted port. A
  path, query, fragment or trailing slash is rejected. Classroom QR links are
  that origin plus `/classroom/{token}`. CSRF accepts only that exact origin.
  The origin has not been verified in a browser.

The protected operator file is not in git. It must set `MAYA_DOMAIN`,
`ACME_EMAIL`, a `SESSION_SECRET` of at least 32 bytes, and absolute
`MAYA_PRODUCTION_DATA_DIR` and `MAYA_PRODUCTION_CONFIG_DIR` paths. Do not put a
sample domain, address or certificate in that file until the owner supplies
them. Provider keys, when used, follow
[REAL_PROVIDER_SETUP](REAL_PROVIDER_SETUP.md) and stay in the same uncommitted
file. Putting `CLASSROOM_PUBLIC_BASE_URL` in the file does not change the
production service: the override replaces it with `https://${MAYA_DOMAIN}`.

The domain and server exist. Start the public stack only with the protected
operator file on that server. Do not invent a certificate; Caddy obtains it
at start, and that had not happened as of this record.

## Production startup

For a public deployment use `docker-compose.production.yml` as an explicit
override and a separate project on the new server. Provide `MAYA_DOMAIN`,
`ACME_EMAIL`, and absolute `MAYA_PRODUCTION_DATA_DIR` /
`MAYA_PRODUCTION_CONFIG_DIR` paths in a protected operator environment file
outside the repository. The data directory is writable application state; the
config directory is mounted read-only. Keep these paths separate from local
Demo unless you deliberately migrate a verified complete backup. `.env`,
account catalogs, keys, certificates and this operator file stay uncommitted.

Provision `production-accounts/accounts.private.md` inside that config directory,
using the existing account-catalog format and owner-only permissions. Supply a
real Teacher identity with a strong individual password; do not copy the example
placeholder or Demo password into public service. No public Teacher registration
or passwordless identity switching is enabled. An already provisioned database
Teacher with an independent password is also supported; startup does not replace
that password with the catalog value. Open student self-registration and the
existing classroom password policy remain explicit product behavior.

Set a managed `SESSION_SECRET` of at least 32 bytes. When migrating existing data,
keep the original secret and required private configuration: it also protects
stored encrypted values, not just login sessions. Configure real Providers and
reviewed policies using [REAL_PROVIDER_SETUP](REAL_PROVIDER_SETUP.md); Mock mode
is not real AI acceptance. Never print the expanded Compose configuration or
commit operator environment, account catalogs, keys, data, or provider policies.

`PROVIDER_STANDING_CONSENT=true` records the operator's one-time consent for the
reviewed Providers, so teachers and students see no disclosure screen. It does not
skip authorization: every exact manifest is still confirmed, ledgered and deduplicated,
and unknown acceptance is still never resent. Leave it unset to require a Teacher
confirmation instead.

```sh
docker compose --project-name maya-production --env-file /protected/maya-production.env \
  -f docker-compose.yml -f docker-compose.production.yml \
  up -d --build --wait
```

The override exposes only Caddy on HTTP/HTTPS and persists its certificate state.
It requires public HTTPS, disables all Demo identity/automatic-consent switches,
and keeps backend/frontend ports inside Docker networks. Caddy replaces the client
address forwarded to the backend; do not enable its trust flag on a directly
reachable backend or another proxy without equivalent isolation and sanitization.
Validate DNS/certificates, redirects, secure cookies, QR, SSE/WebSocket and the actual
site after deployment; offline config checks cannot verify a public certificate.

Production authentication defaults are 10 failed sign-ins per account/client in
15 minutes, 240 failed sign-ins per client in 15 minutes, and 120 registrations per
client in an hour. Successful sign-ins do not consume failure allowances. Operators
can configure the documented `AUTH_*` environment values; denials state a retry delay
and retain legitimate sessions. These protections exist only at authentication
endpoints. Caddy's 16 KB request limit applies only to login/register; its HTTP 413
is an edge response, while application 403/429 use the platform error envelope.
This stage has no Chat, Tool, content, generation-count or fee quota.

Arrange protected regular backups and an operator-owned off-host destination before
public use. A backup must include SQLite via its backup API, referenced runtime
files, private configuration, effective environment and compatible image/source SHA.
Check DB/file receipts and rehearse restoration separately. The current repository
procedure does not provision an external backup account, schedule or monitoring
service, and does not claim an operational RPO/RTO that has not been measured.
