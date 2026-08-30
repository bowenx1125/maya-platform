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
