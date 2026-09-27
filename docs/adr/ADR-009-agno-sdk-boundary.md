# ADR-009: Pin Agno 3.0.11 for the MayaForm runtime

**Status:** ACCEPTED  
**Date:** 2026-09-27

## Context

MayaForm needs public Agent, Team and Toolkit execution while Maya retains
identity, authorization, persistence, provider accounting and result projection.
The SDK must not silently add retries, fallback models, output/history limits,
cross-request state or public worker tools.

## Decision

Pin `agno==3.0.11` directly in the Python backend. Use its public `Agent`,
`Team`, `Toolkit`, `RunContext` and `Model` APIs through thin adapters; do not
copy or vendor SDK code. Register only explicit Toolkit methods. Keep permission
checks in Maya application services, which must authorize each call even when
Agno hides and injects `RunContext`.

Create fresh Agent, Team and Toolkit instances for each server-authorized
invocation. Pass `cache_callables=False` and `cache_results=False`; set
`telemetry=False`, `stream_member_events=False`, `retries=0`,
`retry_with_guidance=False`, `retry_with_guidance_limit=0`,
`fallback_config=None`, `fallback_models=None`, and `tool_call_limit=None`.
Disable automatic history, memory, team-history and member-interaction sharing;
Maya assembles the complete authorized transcript explicitly. Use
`TeamMode.coordinate`, not Agno's task mode, whose public default
`max_iterations=10` is a finite progress gate. A fake Model passed eleven
sequential tool steps through the public Agent path with no default tool limit.
The base Model API exposes no `max_tokens` setting; provider-specific output
limits remain to be checked when Maya binds its model adapter.

For complete Team history, do not pass `List[Message]` as `Team.run(input)`:
the SDK joins user messages and drops assistant messages. The tested public path
sets the complete prior transcript on `Team.additional_input`, passes only the
current Message to `run`/`arun`, and gives each fresh member Agent
`additional_input=[*history, current_user_message]`. With automatic history and
member sharing disabled, sync and async runs preserved 25 long messages exactly
(role, content, order and speaker name) through leader follow-up and two member
delegations; one member did not receive another member's private prompt or
same-run reply. W2 must use this path in the real adapter and retain this
regression.

Agno confirmation pauses before the tool side effect, and
`stop_after_tool_call` returns a completed RunOutput without another model call.
The public `RunOutput.to_dict/from_dict` round trip supports confirm/reject with a
fresh Agent after each restored requirement is rebound to its matching tool
execution by `tool_call_id`. Replaying a confirmed old checkpoint can repeat its
tool side effect, so Maya must keep write idempotency and persisted run/ledger
state as business truth. W0 does not prove provider acceptance recovery or
service-level authorization; W2 must test those at the Maya service boundary.

Only reproducible failures of public extension points justify proposing a minimal
upstream SDK change/port with regression tests. Do not vendor source as a
workaround or bypass Maya authorization, idempotency or evidence checks.

## Provenance and W0 evidence

PyPI release: [agno 3.0.11](https://pypi.org/project/agno/3.0.11/), not yanked,
Apache-2.0, Python `>=3.9,<4`. The upstream `v3.0.11` tag resolves to commit
[`8063a7ec3ac6ab4902bdc7966870d3b5c5f51ffc`](https://github.com/agno-agi/agno/tree/v3.0.11).
The pinned distributions recorded
in `backend/uv.lock` have these SHA-256 hashes:

- Wheel `agno-3.0.11-py3-none-any.whl`: `2517e8524739956648f4b62e6cf568623986144fa1426e430ace14efa1b78257`
- Source archive `agno-3.0.11.tar.gz`: `8e625ebea5265f0cf47b5dafbd749b0e6feb226f8b14f230e2674f5ded41fb7f`

`backend/tests/test_agno_sdk_contract.py` binds its probes to version 3.0.11,
blocks and counts socket attempts, and uses only synthetic Model responses.
It covers hidden context injection, full Agent history, the tested Team history
path and direct-list counterexample, multi-member delegation/isolation,
callable-factory isolation, retry defaults, confirmation serialization/recovery
and stop behavior. No Provider or telemetry call is part of the evidence. These
probes establish SDK extension behavior, not product acceptance.
