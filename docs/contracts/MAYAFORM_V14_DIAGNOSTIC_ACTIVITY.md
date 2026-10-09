# MayaForm v1.4 persistent assessment activity contract

The [adopted Resume v2 contract](MAYAFORM_V14_BRAINFORM_ASSESSMENT.md) is authoritative.
Practice and configured formal diagnosis remain available; no mandatory Teacher
mode panel or manual activity-approval ceremony is introduced. Agent.md and the
authorized recipe guide teaching; stable server activity identity binds attempts
independently of Chat, names, model runs and UI navigation.

The editable [teaching Agent.md examples](../examples/mayaform-diagnostic/README.md)
declare the Leader recipe and evaluator/summarizer roles explicitly. They are
importable teaching content, not preapproved execution grants. Ordinary Agents
and Teams need no assessment declarations.

Chats uses the same ordinary composer and message history for every entry type.
Attempt state does not introduce a dashboard, state/progress card, dedicated input
or lifecycle button group. Natural-language actions use the real Agent and registered
assessment tool; paused queries stay paused, and only a valid continue action resumes.
Permissions and state errors reuse ordinary messages and existing error presentation.

Only configured assessment Maya Teams activate the local no-hint protocol. One
unfinished attempt exists per actor/activity; unrelated activities and ordinary
Chats remain usable. New entry resumes the original attempt and original privacy.
Pause, disconnect, refresh, output stop and failure preserve answers/current question.
Explicit abandon-and-redo closes the original attempt and creates exactly one
new ID atomically. The latest user decision discards abandoned learning records;
its Tool/prompt and data-disposition implementation is explicitly deferred. Current
retention is not acceptance of that decision, nor authority to purge billing history. After all selected questions are resolved, the authorized
executor saves Assessment and Boundary. The final successful Boundary write and
server completion event share one transaction; no extra student confirmation is
required. Missing evidence, paused/withdrawn state or failed writes cannot complete
the attempt. Exact receipt recovery must not create new revisions. Raw answers/skips
append; immutable question/Rubric versions are pinned when presented. Historical
hinted records remain accurately labeled.

Active student channels provide original answers and progress, never solutions,
hints, explanation, correctness, scores, weaknesses or internal Rubric. Structured
semantic protocol separates a valid answer from any accompanying unrelated request.
Internal evaluator context/results never enter member replies, Memory, Tool results,
SSE or source previews. Ended attempts permit ordinary authorized discussion.

Teacher reports require current course permission, published-course provenance,
Public original privacy and non-withdrawn eligible evidence. Denominators exclude
Private, ordinary Public and student Custom Teams. Count distinct people, attempts,
completed, abandoned, active/paused and effective answers separately. Recheck all
eligibility on query/download; retained old report IDs cannot bypass withdrawal.

Chat deletion is a tombstone/withdrawal with in-flight and late-write fencing. Keep
raw evidence and billing history, remove teacher eligibility, preserve recoverable
attempt state; no foreign-key error or cascade deletion of raw answers.

Implementation and browser/Provider acceptance are recorded separately in
[BF/AT/RS](../validation/MAYAFORM_V14_INTEGRATED_ACCEPTANCE.md), not assumed here.
