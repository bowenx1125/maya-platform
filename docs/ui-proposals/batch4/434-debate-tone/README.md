# 434 · Debate card tone → TTS instruction → Voice Preview

Issue: https://github.com/bowenx1125/maya-platform/issues/434

## Current state

- Compiled Debate card already has **Speaking style** (LLM persona text) and
  **Voice** (`voice_style`, vocal delivery line).
- When a card is `ready`, `voice_params_with_card` already copies `voice_style`
  into TTS `instruction` for debate speech.
- Voices library **Preview** synthesizes a rotating sample line and does **not**
  send that card tone / instruction, so Preview can diverge from debate speech.
- Debate create still has debate-wide `voice_params.instruction` (fallback when
  the card has no voice line).

Assets:

- `assets/current-check-card-1440.png`
- `assets/current-check-card-390.png`
- Interactive sheet: `mockups.html`

## Options (pick one)

### A · Tone label (rename Voice → Tone)

What changes

1. Check card label **Voice** → **Tone** (same underlying `voice_style` value).
2. Add **Preview with tone** on the Check card (or Voices Preview when opened
   from a debate context) so Preview TTS uses the same instruction string as
   debate speech.
3. Compile prompt / teacher-facing wording talks about Tone as the delivery line.

What stays the same

- Speaking style stays for rhetorical habits in the LLM prompt.
- Card JSON key can stay `voice_style` (display-only rename) to avoid churn.
- Existing Check card / Preview test hooks stay unless a new Preview control needs
  a new `data-ui-guide` only.

Mockups: `assets/option-a-1440.png`, `assets/option-a-390.png`

### B · Tone sticker field

What changes

1. Tone is shown as a yellow sticker chip on the Check card (still the TTS line).
2. Preview button sits under that chip; Preview audio always uses Tone.
3. Speaking style remains a plain field; Voice key can remain in JSON as today
   or be aliased as Tone in the UI only.

What stays the same

- No new helper paragraphs; sticker + button only.
- Debate speech wiring stays “ready card delivery line wins over debate-wide
  instruction”.

Mockups: `assets/option-b-1440.png`, `assets/option-b-390.png`

### C · Tone + Preview strip

What changes

1. Tone lives in its own bordered strip with a small **TTS** sticker and a
   **Preview** control.
2. Strongest visual link between Tone text and Preview playback.
3. Same instruction string feeds debate speech and Preview.

What stays the same

- Speaking style field unchanged.
- No Voices album redesign beyond accepting an instruction when Preview is
  debate-scoped.

Mockups: `assets/option-c-1440.png`, `assets/option-c-390.png`

## Numbered change notes (all options)

1. **Data model:** Prefer keeping tone inside `card_json` (already a JSON blob on
   `DebateParticipant`). Do **not** add a new SQL column unless product later
   wants tone editable outside compile.
2. **Migration:** **No Alembic migration** if Tone maps to existing
   `voice_style` (or a JSON rename with dual-read). **OpenAPI / generated
   schema** update only if the public field is renamed or a new property is
   added. Call that out in the implement PR; do not write the migration in this
   proposal batch.
3. **Card generation:** Compile prompt must name Tone explicitly (or keep
   `voice_style` wording if A keeps the key). Fail closed on over-long lines
   (existing `CARD_MAX_LINE_CHARS`).
4. **TTS instruction wiring:** Keep `voice_params_with_card`: ready Tone wins;
   else debate-wide `instruction`; else env default.
5. **Preview behavior:** `create_voice_preview` (or a debate-scoped preview
   path) must accept the same instruction string used for speech. Sample lines
   can stay; tone rides in `instruction`.
6. **UI:** English only; neobrutalism; shared buttons/tags; no `?` / helper
   paragraphs. Implementation must match the approved mockup exactly.

## Recommended lean path

If the goal is “previews match debate speech” with minimal surface: **A**
(rename + Preview uses instruction). Choose **B** or **C** if Tone needs a
stronger visual sticker treatment.
