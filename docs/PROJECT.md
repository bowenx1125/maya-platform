# Maya Platform

Maya teaches through published Agent Markdown, group knowledge, classroom
debates, student messages and reports. This file is the single product and
progress record; [AGENTS.md](../AGENTS.md) is the working agreement. Stable
contracts and architecture live in [contracts](../contracts/),
[ADRs](adr/), and [ARCHITECTURE.md](ARCHITECTURE.md).

## Runtime and access boundaries

The demo uses Next.js, FastAPI, SQLite/local files and Caddy on port 8080.
Preserve private configuration and runtime data. Teachers access course and
group records through course membership; entering a workspace is an explicit
membership action. Published Agent versions and knowledge snapshots are
immutable. Workspace deletion retains immutable assets and private chats
read-only; active publications or Debate references block deletion.

Teacher Components can save the installation-wide DashScope key encrypted;
the server environment key takes priority. Provider checks disclose the
maximum calls before sending and stop on failure. LLM, Embedding and Report can
use configured providers; defaults and all TTS/Voice services remain Mock or
Deferred unless explicitly configured. No credentials, provider responses or
student data belong in browser DTOs, logs or this record.

## Debate and classroom contract

New Debates use exactly four rounds and two to five Agents. The protocol is
`ordered_multi_expert_mutual_learning_v1` with `segments_v2` and
`four_round_v1` snapshots. Opening uses each Agent's own evidence; Discussion
addresses specific claims and a stable assigned Agent; Response considers
questions and records concise session memory; Conclusion compares public
speeches with each Agent's own evidence. Other Agents' knowledge and Persona
remain private. Disagreement may remain. Existing records are not silently
regenerated or deleted.

Preview stores exact text and Mock audio for rounds one to three; round four is
generated live. Successful prior turns and accepted stages are reused. A
provider result with unknown acceptance is not automatically resent. Speech
length guidance is in the System Prompt only; the backend does not truncate,
pad, repair or reject text by length. Direct support, contextual support and
no-match are evidence-support categories, not correctness scores. Content
acceptance checks real answers, evidence and reasoned disagreement, not string
similarity. Prompt examples are in
[FOUR_ROUND_PROMPTS.md](contracts/FOUR_ROUND_PROMPTS.md) and
[four-round-example.json](contracts/four-round-example.json).

Default Debate Rules live in the two Markdown files under
`backend/app/modules/debates/default_rules/`. Creating a Debate freezes both
language versions and the complete System messages. Editing defaults cannot
change a saved Debate; unsafe HTML and links are rejected. Report revisions
remain immutable and reviewable. Network recovery does not advance playback or
automatically generate another turn.

Classroom display supports two to five licensed figures around the courtyard
table. Jaw motion, speech bubble and Transcript follow audio; saved text stays
readable if media fails. `/local-roundtable` accepts a local generated WAV
directory. Cloned voices belong to their uploader. Optional Gaussian scene
packs remain local experiments described by [ADR-007](adr/ADR-007-courtyard-splat.md).
Real speech and classroom-scale acceptance remain unverified.

## Workspace, Chats and Live

Agent Markdown is authored directly in Chinese or English with a 12,000
character cap. RAG files allow up to 100,000 characters each; no chapter parser
or semantic mastery inference is promised. Chats are owner-bound, freeze a
published version and snapshot, use request identity and cost accounting, and
stop when provider acceptance is unknown. Live viewers share public content
and retained audio, not controller messages or a new generation per viewer.

Chats streams use `POST /api/v1/conversations/{conversation_id}/messages:stream`.
The assistant text commits once before `text_done`; later TTS failure does not
remove it. TTS runs once after text completion, and `tts_ready` carries an
`audio_url`. Student voice enrollment stores the external voice ID encrypted;
voice rows do not store API keys. DashScope speech may be enabled only with
`DASHSCOPE_API_KEY`; no charged speech call was made in the acceptance records
below. The semantic API audit covers both conversation streaming and deletion;
the frozen delete contract includes the existing 409 Conflict for a deleted
Agent.

The non-login visual language uses warm paper cards, display-serif section
headings and the Mayaform navigation mark. Selected Workspace and Debate
controls and section headings carry bilingual hover, focus and touch guidance;
ordinary controls and headings without guide metadata do not show a tip.
Library tiles use quiet edit, download, delete and reindex actions. Back/Done remain contextual. Chats keeps
saved history on reentry; a model switch starts a new conversation.
Focus-anchored guide tips reposition after page scroll and viewport resize, and
keep their accessible description when the locale changes. Component tests
cover pointer, keyboard, touch dismissal and viewport-edge placement.

## Recorded acceptance and provider ledger

On September 22, one Ready three-Agent Debate completed Start, Next,
Interact/Hide, Check RAG, four rounds and 12 turns, Conclude and Version 1
Report. Reload and Replay preserved it. Nine Preview speeches were reused.
Seven charged calls succeeded: three Embedding queries, three final LLM turns
and one Report. Replay and reopening Report added none. TTS/Voice were Mock;
no student messages or votes were sent. A later dated ledger recorded 17
successes (7 Embedding and 10 LLM/check calls); these historical counts do not
describe the current checkpoint.

On September 23, snapshot work accepted and staged one batch; the next actual
request returned DashScope HTTP 500. The continuation policy allowed one retry
of that rejected batch, but the
preserved record does not establish whether a second request was sent, so it is
not counted here. A later build accepted five batches, then timed out after 30
seconds on one batch (`acceptance_unknown`); the following two were `not_sent`.
The old timeout batch was not resent: after the draft was saved, the next
publish started a new build. At 07:28 UTC all nine batches in that build
succeeded. SiyaH's two supplier-accepted batches were restored locally after a
database commit failure at 07:39 UTC, without another supplier request.
Published snapshots used `text-embedding-v4`, dimension 1024; the recorded
outputs contained 12 and 7 chunks. These outcomes remain on their ledgers.

Earlier Chat browser acceptance covered both identities, owner-only history,
Components/Accounts, desktop and 375px layouts, Replay and Live. That release
made 11 assistant-paid calls; concurrent user work later brought that dated
ledger to 17 successes. The last Chat change removed product I/O caps but did
not include a new charged SiyaH run or RAG-quality acceptance. Supplier
capacity and teaching quality remain unverified.

## Workspace file conversion — September 29, 2026

Workspace Evidence, group Knowledge and teacher Courseware accept Markdown,
PDF and Word DOCX. The Maya server runs its bounded `pypdf` preflight first,
then applies bundled RapidOCR locally only to PDF pages with no selectable text
and nonempty page content; a mixed PDF sends only those pages through OCR. OCR
accepts at most 50 pages at 150 dpi with ONNX Runtime limited to two intra-op
and one inter-op thread. Scanned pages are rasterized with pypdfium2 5.13.0 and
recognized through RapidOCR's direct image API. The pypdfium2 wrapper is
licensed Apache-2.0 or BSD-3-Clause. Keep its installed `licenses` tree,
including the PDFium `BUILD_LICENSES` files, with any redistributed backend
runtime. On Windows x64, the installed
pypdfium2 distribution including PDFium and license metadata measured 8.1 MB;
the removed `rapidocr-pdf`, PyMuPDF and `filetype` files measured 55.7 MB in the
same environment, a net reduction of 47.6 MB. OCR output is marked for teacher
review. The detector, classifier and recognizer models are bundled with the
`rapidocr==3.9.2` wheel, which is 27,275,208 bytes (about 26.0 MiB, including
all three models). The Windows x64 ONNX Runtime wheel is 14,311,470 bytes
(about 13.65 MiB). Processing does not download a model or send document
content to a cloud service. Only the converted Markdown is retained. Uploads
are capped at 10 MB, PDFs at 200 pages, and extracted text at 100,000
characters. Text inside images
embedded in DOCX is not OCR-processed. Page headings in converted PDFs are
labels, not reliable page citations in later RAG results. Document workers
retain a 512 MB memory limit, 20 CPU seconds and 30-second parse-result timeout
for selectable-text/PDF and DOCX fast paths. When OCR is required, that same
worker is extended to 1,536 MB and at most 60 CPU seconds and 60 seconds total
parse-result wait; only one OCR worker may run at a time, with at most two
document workers total per server process. Startup and cleanup are outside the
result timeout. DOCX packages are capped at 1,024 parts, 20 MB per part and 64
MB expanded total. Knowledge upload and replacement claims renew to 90 seconds
before conversion. Conversion of arbitrary file formats is not implemented;
formats outside Markdown, PDF and DOCX are rejected.

On September 29, after switching PDF rendering to pypdfium2 and using RapidOCR's
direct image API, the two teacher-provided `future aspects of Chinese
civilization` PDFs completed the isolated conversion function under the Windows
Job Object limits: the 12-page deck produced 7,574 Markdown characters with 12
OCR-marked pages; the 32-page deck produced 13,640 characters with 32
OCR-marked pages. That conversion run read the source PDFs without uploading
them. On October 3, the originals were selected through the browser file picker
in a separate, local isolated Maya test stack: a synthetic teacher account
uploaded both to group Knowledge, and the page showed the pending
conversion/indexing state followed by success; both library entries were ready
with the same character counts. A synthetic student account also uploaded the
12-page PDF to a draft Agent's Evidence page; the RAG preview showed one ready
file with 7,574 characters. This was a local Windows browser acceptance run
using an isolated database and temporary data directory, not a macOS run or a
production teacher account. No provider request or RAG answer-quality test was
made. The Markdown includes a teacher-review marker on every OCR page; the
extraction run does not establish that every recognized word is correct.

On October 4, a separate synthetic DOCX fixture was uploaded through the local
browser file picker to the isolated group Knowledge page. The page showed the
converted `isolated_docx_acceptance.docx.md` entry as ready with 219 characters.
The specified courseware folder contained no DOCX, so this checks the upload
path with a small synthetic document rather than the teacher's Word courseware.

The uploader shows a pending status while upload, conversion and indexing run,
and reports unsupported formats, missing text, size limits and safely stopped
parsing separately. If upload succeeds but the RAG preview refresh fails, the
success remains visible and a separate Retry refreshes only the preview.
Teacher courseware is read-only in the shared library; a teacher can retry a
failed index. Legacy documents predate uploader-role tracking and migration
0033 conservatively labels them student-owned; their historical authors cannot
be safely inferred. Current backend and frontend tests cover conversion,
limits, idempotent replay, role access and Workspace status copy; the isolated
browser walkthrough exercised both the teacher PDF uploads and a synthetic
DOCX upload. The full frontend suite also checks upload-guide copy and
description restoration.
The public roundtable tooltip was visually checked; the camera-control bubble
was adjusted to avoid covering neighboring controls and rechecked. During the
October 3 isolated Workspace walkthrough, screenshots at the browser's narrow
default viewport and at 1366x900 were visually inspected; no obvious overlap or
clipping was observed in the tested upload and Evidence states. The “New” action
tooltip appeared on keyboard focus. On October 4, a 1280x720 browser check
confirmed the Knowledge row's Edit tooltip no longer covers the adjacent DOCX
filename; the Import a file tooltip also moved above its control instead of
covering the format and OCR guidance. Upload help is now explicitly attached to
Agent Markdown, Agent Evidence, Knowledge import and voice-sample file controls.
Guide tooltips still cover selected controls and section headings, not every
button and heading. Component tests simulate pointer, focus and touch events;
the browser check does not establish a full pointer-hover sweep, real touch
behavior or macOS visual acceptance.
The read-only chat composer shows and associates its explanation for keyboard
and screen-reader users.

## Remaining scope

徐伯闻 owns content acceptance; 古月 owns 3D, voice and TTS; Kaikai owns
accounts and student UI. Full RAG quality, real speech, classroom-scale load,
public deployment, monitoring and backup/restore remain unverified. The
teacher Components switch still leaves TTS and Voice deferred. When `LLM_MODEL`
is unset, the server currently uses `qwen3.8-max-2026-09-02`; a charged
acceptance run on that snapshot has not been recorded. Embedding and speech
models remain separately pinned.
