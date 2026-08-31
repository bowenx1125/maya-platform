# W4-G0 Required Decisions

Status: `FROZEN / REAL EMBEDDING 1024 DELTA`

1. **Why write AGENT.md?** It is student authorship compiled into a confirmed Persona
   that visibly controls six expression/argument dimensions.
2. **What may Persona change?** Tone, value priority, argument pattern, concession
   style, question style and debate strategy.
3. **What may Persona never change?** Facts/source bytes, evidence IDs, platform rules,
   permissions, schedule/state machine, language, safety validation or output schema.
4. **How is raw AGENT.md compiled/confirmed/versioned/downloaded?** By the strict local
   PersonaSpecV1 grammar and CAS state machine; raw and canonical hashes remain on the
   immutable AgentVersion and raw remains downloadable. All new Mock and real W4
   debates require confirmed Persona; legacy output is read/replay-only.
5. **How does each RAG source map to a claim?** Server query/receipt IDs and exact
   speech spans form immutable EvidenceTraceV1 rows; only used receipts are public.
6. **How is no-match explained?** “No relevant evidence found; this claim is general
   reasoning; no source is attached.”
7. **Which factual claims require evidence?** Every concrete quantity or explicit
   attribution to an expert, study, survey or report requires direct evidence; the
   existing server detector is the minimum enforcement set.
8. **Maximum input per turn?** 32,000 model tokens; output request 1,500 tokens.
9. **Maximum Provider calls per debate?** 20 Debate LLM calls for 5 Agents × 2 rounds;
   LLM-B and TTS have separate non-transferable caps.
10. **When may attempt 2 retrieve again?** Only after retrieval technical failure
    before any LLM request. Structural repair reuses the frozen receipt set.
11. **What is sent externally?** The exact allowlist in ProviderDataCallV1: structured
    current Persona, topic/rules, complete RuleSet-visible prior speeches (all earlier
    rounds for mutual learning, never same-round), current queries and evidence
    excerpts, opaque IDs and current TTS speech where applicable. The teacher
    sees the supplier, Beijing region, purpose, storage fact and no-training basis
    before confirming the exact export manifest.
12. **Are student names, nicknames, audio or identity sent?** No. Voice enrollment is
    a separate TTS Gate using one approved sample and is not an LLM/Embedding input.
13. **Fixed model versions?** `qwen3.7-plus-2026-05-26`, `text-embedding-v4` at 1024
    dimensions and `qwen3-tts-vc-2026-01-22`; no `latest` fallback.
14. **Maximum charge?** CNY 0.15/request and CNY 3.00 per full Debate LLM run; other
    operation caps are the table in ProviderDataCallV1. Embedding additionally limits
    each item to 8,000 counted tokens and each ten-item request to 30,000.
15. **How do budget/timeout/shape/uncertain failures close?** Pre-send violations make
    zero calls; a durable atomic reservation precedes network I/O; repair uses one
    frozen retry; acceptance-unknown consumes the cap and is never retried or
    published; safe codes hide supplier details.
    W4-LLM-A uses an independent `llm_debate_turn` budget bucket, an immutable accepted
    stage and one atomic Turn/Evidence/usage/operation publication transaction as frozen
    in `LLM_A_RUNTIME_V1.md`.
16. **Which Gates are fully Mock-completable?** W4-PERSONA, W4-RAG-TRACE, W4-PROMPT and
    W4-CONTENT. Their G1/G2/G3 must finish before real Provider evidence.
17. **When does billed work begin?** Two isolated account preflight calls already
    occurred: one 256-dimension Embedding request and one structured LLM request, both
    with non-student fixtures while Maya's selectors stayed Mock. They are availability
    evidence only and are not Gate evidence. The separately authorized W4-EMBED 1024
    preflight later used exactly one safe three-text request; HTTP was 200 but local
    response parsing failed closed, so its status is `REAL EMBEDDING 1024 PREFLIGHT
FAILED` and it must not be repeated under the current Gate. The account must be a verified
    pay-as-you-go API or Token Plan Team account with an accepted
    ProviderPolicySnapshot; personal/Coding/unknown plans stop at zero calls. The
    user's standing authorization removes a repeated per-call confirmation, but no
    Gate or cap. A 256, 1024 or LLM preflight must not be repeated.
