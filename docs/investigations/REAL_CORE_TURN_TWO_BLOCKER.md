# Why the Real-Core run stops at the second turn

Status: open. Turn 1 of the acceptance debate parks correctly and is then
terminated, which fails the whole Debate. Everything before it works.

## What already works

A real acceptance run reaches and passes these, verified by running it:

1. Snapshot embedding, charged once, bound as call 1.
2. Debate created and bound to the acceptance run.
3. Turn 0 (slot A, the Mock-snapshot baseline) parks on its LLM manifest, the
   teacher confirms it, the request is sent, and the reply passes both the
   output mapper and the mutual-learning validator.
4. Turn 0 publishes: `final_ready` / `public`, 98 words, `retrieval_status`
   `matched`, `grounding_mode` `mixed`, evidence trace attached.
5. The server auto-prepares the successor and turn 1 parks on its **retrieval
   query** manifest, emitting `provider_confirmation_required`.

So the real embedding, the real debate LLM, the manifest/disclosure/ordinal
chain and the structure repair all work end to end.

## The failure

Recorded event sequence for one run:

```
1 debate.started
2 round.started            round_no=1 turn_count=2
3 turn.preparing           slot=A stage=llm
4 error                    provider_confirmation_required     <- turn 0 parks
5 turn.preparing           slot=A stage=llm                   <- after confirmation
6 turn.ready               retrieval_status=matched
7 error                    provider_confirmation_required     <- turn 1 parks
8 playback.started                                            <- turn 0 plays
9 debate.failed
```

Final state:

| row                                   | value                                     |
| ------------------------------------- | ----------------------------------------- |
| `provider_operations` embedding       | `succeeded`, charged 1, `call_no=1`       |
| `provider_operations` llm_debate_turn | `succeeded`, charged 1, `call_no=2`       |
| `provider_operations` embedding_query | **`prepared`**, charged 0, `call_no=NULL` |
| `debate_turns[0]`                     | `final_ready` / `public`                  |
| `debate_turns[1]`                     | `turn_generation_failed`                  |
| `jobs` for turn 1                     | `failed`, `turn_generation_failed`        |
| debate                                | `failed`, playback `stopped`              |

The query was never sent, so this costs nothing beyond the two calls already
made. The driver then reports `playback_ack_not_observed`, which is a
consequence, not the cause: it waits for turn 0 to reach `waiting_next` while
the Debate has already failed underneath it.

## Cause

Event 7 proves the park itself succeeded. `_defer_provider_preparation` stages
that error only after `defer_turn_job` returns `True`, and that helper sets the
job to `pending` and the turn back to `pending`.

Between events 8 and 9 the turn is prepared a **second** time and that attempt
fails terminally with the generic `turn_generation_failed` rather than parking
again. The second run is what fails the turn and, through
`fail_turn_and_debate`, the whole Debate.

Two things make the second attempt behave differently from the first:

- `defer_turn_job` refuses when `claim_token is None`
  (`sql_repository.py`, first guard). A re-preparation that runs without
  claiming the job therefore cannot park and falls through to the terminal
  handler.
- Its `UPDATE` also requires the job row to still be `state='running'` with the
  same `claim_token` and `cancellation_generation`. A re-entry that does not
  reproduce that exact fence returns `False` for the same reason.

What has not been established is **which** path re-prepares turn 1 while turn 0
is playing: the successor enqueue after the started/ended acknowledgement, the
task manager picking the job back up now that it is `pending`, or both racing.

The generic code is the tell. `turn_generation_failed` is the default the
playback service uses when the raised error is not in `_SAFE_GENERATION_CODES`.
The first attempt raised `provider_confirmation_required`, which is in that set.
So the second attempt either raised a different exception, or raised the same
one somewhere the safe-code mapping does not apply.

## How to find it in one run

Application logging inside the container never surfaced these warnings even
after a stdout handler was added, so the database and the event table are the
reliable channel. Add a temporary stderr probe — the pattern that worked
repeatedly during this investigation — at the two places that decide the turn's
fate, then run once:

```python
# playback/service.py, in prepare_turn's `except Exception as exc:` block
import sys as _s, traceback as _t          # TEMP
print("TEMP turn failure", file=_s.stderr, flush=True)
_t.print_exc(file=_s.stderr); _s.stderr.flush()
```

```python
# playback/sql_repository.py, at the top of defer_turn_job
import sys as _s                            # TEMP
print(f"TEMP defer claim_token={claim_token!r} code={code}", file=_s.stderr, flush=True)
```

Then reproduce **without spending a provider call**: set `EMBEDDING_PROVIDER`
and `MAYA_REPORT_PROVIDER` to `mock`, leave `LLM_PROVIDER=dashscope`, and run a
debate between two seeded baselines. Their snapshots carry the Mock embedding
identity, so retrieval never calls a provider, while the LLM path still parks on
its manifest exactly as the real run does. That reproduction loop is free and
was what located every other defect in this chain.

Read the outcome from the database rather than the log:

```bash
docker exec <project>-backend-1 python -c "
import sqlite3; db=sqlite3.connect('/app/data/maya.sqlite3'); db.row_factory=sqlite3.Row
for r in db.execute('SELECT sequence,event_type,payload_json FROM debate_events ORDER BY CAST(sequence AS INTEGER)'):
    print(r['sequence'], r['event_type'], str(r['payload_json'])[:110])
"
```

## Likely fix

Once the second path is identified, the fix is one of:

1. **Do not re-prepare a parked turn.** A turn whose job is `pending` with
   `safe_error_code='provider_confirmation_required'` is waiting for a teacher,
   not for a worker. The enqueue path should skip it until the teacher's
   explicit preparation retry arrives, which is the documented resume seam.
2. **Make the second attempt able to park.** If the re-preparation is
   legitimate, it must claim the job first so `defer_turn_job` can fence on the
   same `claim_token`, instead of reaching the terminal handler.

Option 1 is the smaller change and matches the product rule that a provider-
gated turn resumes only on an explicit teacher action. Prefer it unless the
probe shows the re-entry is doing something else useful.

## What not to change

- Do not widen `_SAFE_GENERATION_CODES` to swallow the generic code. That would
  hide a real terminal failure behind a park.
- Do not add an automatic provider retry. The park exists precisely so the
  teacher, not the server, decides to spend the call.
