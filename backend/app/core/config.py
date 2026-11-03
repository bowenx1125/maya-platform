"""Runtime configuration.

The application deliberately keeps secret-bearing settings on the server.  A
missing or short session secret is accepted only for an explicitly test-mode
process; a normal server fails during startup instead of silently using a
guessable key.
"""

from __future__ import annotations

import os
import re
import secrets
from datetime import timedelta
from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dated snapshot, not the floating qwen3.8-max alias. LLM_MODEL overrides it.
DEFAULT_LLM_MODEL = "qwen3.8-max-2026-09-02"
_LLM_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PUBLIC_DNS_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?=[a-z0-9-]*[a-z])[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


class Settings(BaseSettings):
    """Environment-backed settings used by the Wave 0 backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Names intentionally match the repository .env.example and the frozen
    # provider/security contract.
    node_env: str = Field(default="development", validation_alias="NODE_ENV")
    demo_mode: bool = Field(default=False, validation_alias="DEMO_MODE")
    # Passwordless identity selection is intentionally a separate explicit
    # Demo-only capability: either flag being off must hide the route.
    demo_quick_login: bool = Field(default=False, validation_alias="DEMO_QUICK_LOGIN")
    # Standing consent for the provider data-call disclosure, recorded here
    # rather than implied by DEMO_MODE so the decision is visible in .env and
    # has to be taken deliberately. It only has effect while DEMO_MODE is on.
    # With it off, a person confirms each disclosure exactly as before.
    demo_auto_confirm_provider: bool = Field(
        default=False, validation_alias="DEMO_AUTO_CONFIRM_PROVIDER"
    )
    # The deployment operator's one-time consent for a classroom instance. It
    # records the same exact-manifest confirmations and ledger rows a teacher
    # click would, so teachers and students never see a disclosure screen; it
    # is not Demo-only because a real classroom has no Demo switches on.
    provider_standing_consent: bool = Field(
        default=False, validation_alias="PROVIDER_STANDING_CONSENT"
    )
    session_secret: str | None = Field(default=None, validation_alias="SESSION_SECRET")
    # Classroom sessions are meant to outlive a single lesson: 30 days by
    # default (configurable up to a semester) instead of forcing re-login
    # every lesson.
    session_ttl_days: int = Field(default=30, ge=1, le=400, validation_alias="SESSION_TTL_DAYS")
    classroom_public_base_url: str | None = Field(
        default=None,
        validation_alias="CLASSROOM_PUBLIC_BASE_URL",
    )
    dashscope_api_key: str | None = Field(default=None, validation_alias="DASHSCOPE_API_KEY")
    # Chatform's own key: every Agent and Team chat model call and the RAG
    # retrieval those chats make (formal assessment turns included). Unset
    # means chats share DASHSCOPE_API_KEY. Everything else (voices and TTS,
    # Agent / Knowledge embeddings, Knowledge generation, Debates, reports)
    # always uses DASHSCOPE_API_KEY.
    dashscope_chat_api_key: str | None = Field(
        default=None, validation_alias="DASHSCOPE_CHAT_API_KEY"
    )
    dashscope_workspace_id: str | None = Field(
        default=None,
        validation_alias="DASHSCOPE_WORKSPACE_ID",
    )
    dashscope_region: str | None = Field(default=None, validation_alias="DASHSCOPE_REGION")
    provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="PROVIDER_POLICY_HASH",
    )
    # Real-Core Demo uses endpoint-bound policy hashes per Provider slice.  The
    # legacy single hash remains accepted only when exactly one real slice is
    # selected; dual Real Embedding + Real LLM must provide both values.
    embedding_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="EMBEDDING_PROVIDER_POLICY_HASH",
    )
    llm_model: str = Field(default=DEFAULT_LLM_MODEL, validation_alias="LLM_MODEL")
    llm_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="LLM_PROVIDER_POLICY_HASH",
    )
    report_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="REPORT_PROVIDER_POLICY_HASH",
    )
    deepl_api_key: str | None = Field(default=None, validation_alias="DEEPL_API_KEY")
    # Provider selectors intentionally default to local mocks.  They are
    # server-only switches; no provider identity is returned in API DTOs.
    llm_provider: str = Field(default="mock", validation_alias="LLM_PROVIDER")
    report_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices("MAYA_REPORT_PROVIDER", "report_provider"),
    )
    embedding_provider: str = Field(default="mock", validation_alias="EMBEDDING_PROVIDER")
    tts_provider: str = Field(default="mock", validation_alias="TTS_PROVIDER")
    voice_provider: str = Field(default="mock", validation_alias="VOICE_PROVIDER")
    fallback_voice_profile_id: str | None = Field(
        default=None,
        validation_alias="FALLBACK_VOICE_PROFILE_ID",
    )
    # Operator mapping for immutable baseline characters. Empty means each
    # character uses FALLBACK_VOICE_PROFILE_ID. The value is never a voice id
    # baked into code: ``socrates=<uuid>,laozi=<uuid>``.
    baseline_default_voices: str | None = Field(
        default=None,
        validation_alias="BASELINE_DEFAULT_VOICES",
    )
    # Debates (beta) shows a join code on the stage and flies classroom
    # messages across it while the Agents are still speaking, which the
    # after-the-debate gate forbids.  Off by default: with the switch off the
    # classic Debates surface behaves exactly as it always has.
    debates_beta_live_interaction: bool = Field(
        default=False,
        validation_alias="DEBATES_BETA_LIVE_INTERACTION",
    )
    # Clone target for new voices. A clone stays bound to the model it was
    # enrolled for, so changing this leaves existing clones on theirs.
    voice_clone_model: Literal["qwen-audio-3.1-tts-flash", "qwen-audio-3.0-tts-flash"] = Field(
        default="qwen-audio-3.1-tts-flash",
        validation_alias="VOICE_CLONE_MODEL",
    )

    # Debate generation defaults. Each new Debate freezes these, overridden by
    # the teacher's parameter card, into its snapshot; an empty value means the
    # parameter is not sent. Unset, they match the values Debates ran with.
    debate_llm_model: str | None = Field(default=None, validation_alias="DEBATE_LLM_MODEL")
    debate_llm_temperature: float | None = Field(
        default=0.65, validation_alias="DEBATE_LLM_TEMPERATURE"
    )
    debate_llm_top_p: float | None = Field(default=0.8, validation_alias="DEBATE_LLM_TOP_P")
    debate_llm_presence_penalty: float | None = Field(
        default=None, validation_alias="DEBATE_LLM_PRESENCE_PENALTY"
    )
    debate_llm_frequency_penalty: float | None = Field(
        default=None, validation_alias="DEBATE_LLM_FREQUENCY_PENALTY"
    )
    debate_llm_repetition_penalty: float | None = Field(
        default=None, validation_alias="DEBATE_LLM_REPETITION_PENALTY"
    )
    debate_llm_max_tokens: int | None = Field(
        default=None, validation_alias="DEBATE_LLM_MAX_TOKENS"
    )
    debate_llm_enable_thinking: bool = Field(
        default=False, validation_alias="DEBATE_LLM_ENABLE_THINKING"
    )
    debate_llm_seed: int | None = Field(default=None, validation_alias="DEBATE_LLM_SEED")
    debate_llm_timeout_seconds: float = Field(
        default=120.0, gt=0, le=600, validation_alias="DEBATE_LLM_TIMEOUT_SECONDS"
    )
    # Speech model for voices bound to no model; a clone keeps its own.
    debate_tts_model: str | None = Field(default=None, validation_alias="DEBATE_TTS_MODEL")
    # Voice defaults for cloned voices (qwen-audio-*-tts-flash only; preset
    # voices are never sent these). The speaking rate replaces the browser
    # playback rate: every Debate plays at 1.0.
    debate_tts_rate: float | None = Field(
        default=1.25, ge=0.5, le=2.0, validation_alias="DEBATE_TTS_RATE"
    )
    debate_tts_instruction: str | None = Field(
        default=None, max_length=500, validation_alias="DEBATE_TTS_INSTRUCTION"
    )
    debate_tts_seed: int | None = Field(
        default=None, ge=0, le=65535, validation_alias="DEBATE_TTS_SEED"
    )

    # These server-only operational values are also part of C02/C08. They are
    # intentionally not exposed in browser-facing DTOs. PostgreSQL only.
    database_url: str = Field(
        default="postgresql+psycopg://maya@localhost:5432/maya",
        validation_alias="DATABASE_URL",
    )
    data_root: Path = Field(default=Path("data"), validation_alias="DATA_ROOT")
    demo_users_file: Path = Field(
        default=Path("config/demo_users.yaml"),
        validation_alias="DEMO_USERS_FILE",
    )
    demo_accounts_file: Path = Field(
        default=Path("config/demo-accounts/accounts.private.md"),
        validation_alias="DEMO_ACCOUNTS_FILE",
    )
    # Explicit one-time compatibility switch for a legacy YAML migration. It
    # defaults off so an old YAML file cannot silently become a second runtime
    # credential source after the private Markdown catalog is adopted.
    allow_legacy_demo_users: bool = Field(
        default=False,
        validation_alias="ALLOW_LEGACY_DEMO_USERS",
    )
    maya_env: str = Field(default="", validation_alias="MAYA_ENV")
    auth_login_account_failure_limit: int = Field(
        default=10, ge=1, le=10_000, validation_alias="AUTH_LOGIN_ACCOUNT_FAILURE_LIMIT"
    )
    auth_login_client_failure_limit: int = Field(
        default=240, ge=1, le=100_000, validation_alias="AUTH_LOGIN_CLIENT_FAILURE_LIMIT"
    )
    auth_login_failure_window_seconds: int = Field(
        default=900, ge=1, le=86_400, validation_alias="AUTH_LOGIN_FAILURE_WINDOW_SECONDS"
    )
    auth_register_client_limit: int = Field(
        default=120, ge=1, le=100_000, validation_alias="AUTH_REGISTER_CLIENT_LIMIT"
    )
    auth_register_window_seconds: int = Field(
        default=3_600, ge=1, le=604_800, validation_alias="AUTH_REGISTER_WINDOW_SECONDS"
    )
    auth_abuse_max_buckets: int = Field(
        default=8_192, ge=128, le=65_536, validation_alias="AUTH_ABUSE_MAX_BUCKETS"
    )
    # Retry hint when sign-in hits a locked / overloaded database.
    auth_login_queue_retry_seconds: int = Field(
        default=2, ge=1, le=60, validation_alias="AUTH_LOGIN_QUEUE_RETRY_SECONDS"
    )
    # Concurrent Argon2 hash / verify calls per process (app/core/hash_gate.py).
    # This is memory protection, not a business rate limit: each in-flight call
    # allocates memory_cost (64 MiB) at once, so the default is roughly the CPU
    # core count (2 on the classroom host). 0 disables the cap.
    auth_hash_concurrency: int = Field(
        default=2, ge=0, le=64, validation_alias="AUTH_HASH_CONCURRENCY"
    )
    # Unified pressure signal (app/core/adaptive_admission.py). Below this
    # MemAvailable floor (MiB) or at/above the 1m load reject threshold, new
    # work only queues; it resumes once MemAvailable >= the resume floor AND
    # load <= the resume threshold. Zero disables that half of the signal.
    memory_guard_min_available_mb: int = Field(
        default=500, ge=0, le=1_000_000, validation_alias="MEMORY_GUARD_MIN_AVAILABLE_MB"
    )
    memory_guard_resume_available_mb: int = Field(
        default=550,
        ge=0,
        le=1_000_000,
        validation_alias="MEMORY_GUARD_RESUME_AVAILABLE_MB",
    )
    # Server size (app/core/capacity.py): the CPU-bound loads and caps below
    # were measured on a 2-vCPU host and grow by cores / this baseline on a
    # bigger one, never below 1x. CAPACITY_SCALE pins the multiplier.
    capacity_baseline_cpus: int = Field(
        default=2, ge=1, le=1024, validation_alias="CAPACITY_BASELINE_CPUS"
    )
    capacity_scale: float | None = Field(
        default=None, gt=0, le=64, validation_alias="CAPACITY_SCALE"
    )
    host_load_reject_threshold: float = Field(
        default=6.0, ge=0, le=10_000, validation_alias="HOST_LOAD_REJECT_THRESHOLD"
    )
    host_load_resume_threshold: float = Field(
        default=4.0, ge=0, le=10_000, validation_alias="HOST_LOAD_RESUME_THRESHOLD"
    )
    # Per-operation backstop behind the unified queue: in-flight
    # LLM HTTP attempts per process. Was 12 when this gate alone protected the
    # host (MayaLoad: 10 stable, 20 melted before the adaptive queue existed).
    # #140 sweep (2026-10-18, 40 students, all three backstops 17/14/11/8/5):
    # 8 per backend gave the best throughput and the lowest load. It waits
    # only for what is left of the shared deadline.
    llm_admission_limit: int = Field(
        default=8, ge=0, le=10_000, validation_alias="LLM_ADMISSION_LIMIT"
    )
    llm_admission_queue_max: int = Field(
        default=100, ge=0, le=10_000, validation_alias="LLM_ADMISSION_QUEUE_MAX"
    )
    llm_admission_wait_seconds: int = Field(
        default=180, ge=0, le=3_600, validation_alias="LLM_ADMISSION_WAIT_SECONDS"
    )
    llm_admission_retry_seconds: int = Field(
        default=5, ge=1, le=300, validation_alias="LLM_ADMISSION_RETRY_SECONDS"
    )
    # Required backstop: concurrent Team/Chat turns per process (2 replicas:
    # 16 on the host). The adaptive budget charges a turn once, but a formal
    # turn writes the database 50-90 times over 10-30 s, and the load signal
    # lags. With this off (#133), 20 simultaneous assessment turns drove a
    # 2 vCPU host to load 10 in 29 s (2026-10-18); with a cap they waited in
    # this queue instead. Later turns wait (FIFO, the shared 180 s budget);
    # only a full queue or a spent wait answers write_pressure. 0 disables.
    write_guard_limit: int = Field(default=8, ge=0, le=10_000, validation_alias="WRITE_GUARD_LIMIT")
    write_guard_queue_max: int = Field(
        default=100, ge=0, le=10_000, validation_alias="WRITE_GUARD_QUEUE_MAX"
    )
    write_guard_wait_seconds: int = Field(
        default=180, ge=0, le=3_600, validation_alias="WRITE_GUARD_WAIT_SECONDS"
    )
    write_guard_retry_seconds: int = Field(
        default=5, ge=1, le=300, validation_alias="WRITE_GUARD_RETRY_SECONDS"
    )
    # Debate audience traffic (2026-10-19): votes and barrages pass a small
    # per-process asyncio gate below scoring and chat. Under the danger latch
    # they are refused at once (503) and never take a reserved slot; a full
    # queue or a spent wait answers 503 with retry_after_seconds.
    debate_interaction_gate_limit: int = Field(
        default=4, ge=0, le=1_000, validation_alias="DEBATE_INTERACTION_GATE_LIMIT"
    )
    debate_interaction_gate_queue_max: int = Field(
        default=64, ge=0, le=10_000, validation_alias="DEBATE_INTERACTION_GATE_QUEUE_MAX"
    )
    debate_interaction_gate_wait_seconds: float = Field(
        default=20.0, ge=0, le=120, validation_alias="DEBATE_INTERACTION_GATE_WAIT_SECONDS"
    )
    # Votes/barrages admitted at a time per backend while the danger latch holds.
    debate_interaction_latched_reserve: int = Field(
        default=1, ge=1, le=16, validation_alias="DEBATE_INTERACTION_LATCHED_RESERVE"
    )
    debate_interaction_retry_seconds: int = Field(
        default=3, ge=1, le=120, validation_alias="DEBATE_INTERACTION_RETRY_SECONDS"
    )
    # One barrage per audience member per this many seconds (all backends).
    debate_barrage_cooldown_seconds: float = Field(
        default=3.0, ge=0, le=600, validation_alias="DEBATE_BARRAGE_COOLDOWN_SECONDS"
    )
    # The anonymous form and the live view serve a copy this fresh; under
    # pressure an older copy (up to the stale limit) instead of a database read.
    debate_public_cache_seconds: float = Field(
        default=2.0, ge=0, le=60, validation_alias="DEBATE_PUBLIC_CACHE_SECONDS"
    )
    debate_public_stale_seconds: float = Field(
        default=60.0, ge=0, le=3_600, validation_alias="DEBATE_PUBLIC_STALE_SECONDS"
    )
    # Debate WebSockets: one snapshot per debate shared by every connection,
    # access rechecked every few seconds, a fallback poll when no event wakes
    # them, and one relay task per debate reading new events from the database
    # so viewers on the other backend see them.
    debate_snapshot_cache_seconds: float = Field(
        default=1.5, ge=0, le=30, validation_alias="DEBATE_SNAPSHOT_CACHE_SECONDS"
    )
    debate_ws_auth_recheck_seconds: float = Field(
        default=10.0, ge=0, le=600, validation_alias="DEBATE_WS_AUTH_RECHECK_SECONDS"
    )
    debate_ws_fallback_poll_seconds: float = Field(
        default=7.0, ge=1, le=60, validation_alias="DEBATE_WS_FALLBACK_POLL_SECONDS"
    )
    debate_event_relay_poll_seconds: float = Field(
        default=1.0, ge=0.1, le=30, validation_alias="DEBATE_EVENT_RELAY_POLL_SECONDS"
    )
    # Serve Debate speeches as MP3 (ffmpeg, cached in memory) as well as WAV.
    # Off by default for local runs and tests; production Compose turns it on.
    debate_audio_mp3: bool = Field(default=False, validation_alias="DEBATE_AUDIO_MP3")
    # Per-operation backstop: concurrent Agent/Team/Conversation creates per
    # process. 8 per backend (#140 sweep, 2026-10-18): a class opening its
    # chats at once peaked at 8 here and waited briefly instead of reaching
    # the database together. 0 disables.
    create_admission_limit: int = Field(
        default=8, ge=0, le=10_000, validation_alias="CREATE_ADMISSION_LIMIT"
    )
    create_admission_queue_max: int = Field(
        default=100, ge=0, le=10_000, validation_alias="CREATE_ADMISSION_QUEUE_MAX"
    )
    create_admission_wait_seconds: int = Field(
        default=180, ge=0, le=3_600, validation_alias="CREATE_ADMISSION_WAIT_SECONDS"
    )
    create_admission_retry_seconds: int = Field(
        default=5, ge=1, le=300, validation_alias="CREATE_ADMISSION_RETRY_SECONDS"
    )
    # One request-level queue for login / create / write / LLM (the old
    # per-op login queue folds in; LLM / write / create gates stay behind it
    # as backstops). AIMD sizes a weighted budget from server-side signals
    # only (load, MemAvailable, DB write p95, DB pool wait p95, thread-pool
    # use); request p95 counts queue time, so it is reported, not acted on.
    # Disabling only freezes the
    # budget at max; pressure queueing and the global cap always apply.
    adaptive_admission_enabled: bool = Field(
        default=True, validation_alias="ADAPTIVE_ADMISSION_ENABLED"
    )
    # Single global backstop: admitted requests per process never exceed this,
    # whatever the budget says. A Chat/Team turn holds a write slot and a
    # nested LLM slot (2 entries), so 48 = 20 turns plus room for logins and
    # creates. main.py raises AnyIO's sync-handler pool to 128 threads so 48
    # admitted requests cannot starve /health/ready or plain reads.
    adaptive_admission_max_in_flight: int = Field(
        default=48, ge=1, le=10_000, validation_alias="ADAPTIVE_ADMISSION_MAX_IN_FLIGHT"
    )
    # Max budget 128: 20 turns x 6 units (write 2 + nested LLM 4) = 120, plus
    # room for logins and creates. Min keeps one model call moving.
    adaptive_admission_max_units: int = Field(
        default=128, ge=1, le=10_000, validation_alias="ADAPTIVE_ADMISSION_MAX_UNITS"
    )
    # Cold-start budget (18 LLM calls at weight 4). AIMD climbs to max while
    # the signals stay healthy, and an idle process (30 s, healthy) returns
    # to at least this much.
    adaptive_admission_initial_units: int = Field(
        default=72, ge=1, le=10_000, validation_alias="ADAPTIVE_ADMISSION_INITIAL_UNITS"
    )
    adaptive_admission_min_units: int = Field(
        default=4, ge=1, le=10_000, validation_alias="ADAPTIVE_ADMISSION_MIN_UNITS"
    )
    adaptive_admission_increase_units: float = Field(
        default=2.0, gt=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_INCREASE_UNITS"
    )
    # Growth step while the budget is below half of max: recover faster from
    # a shrink that has passed.
    adaptive_admission_fast_increase_units: float = Field(
        default=4.0, gt=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_FAST_INCREASE_UNITS"
    )
    adaptive_admission_idle_seconds: float = Field(
        default=30.0, ge=0, le=3_600, validation_alias="ADAPTIVE_ADMISSION_IDLE_SECONDS"
    )
    adaptive_admission_decrease_factor: float = Field(
        default=0.7, gt=0, lt=1, validation_alias="ADAPTIVE_ADMISSION_DECREASE_FACTOR"
    )
    adaptive_admission_sample_seconds: float = Field(
        default=1.0, gt=0, le=60, validation_alias="ADAPTIVE_ADMISSION_SAMPLE_SECONDS"
    )
    adaptive_admission_adjust_seconds: float = Field(
        default=2.0, ge=0, le=300, validation_alias="ADAPTIVE_ADMISSION_ADJUST_SECONDS"
    )
    # Soft pressure (shrink, still admit). Danger line reuses
    # HOST_LOAD_REJECT/RESUME and MEMORY_GUARD_MIN/RESUME (queue only).
    adaptive_admission_soft_load: float = Field(
        default=4.0, ge=0, le=10_000, validation_alias="ADAPTIVE_ADMISSION_SOFT_LOAD"
    )
    adaptive_admission_soft_mem_mb: int = Field(
        default=900, ge=0, le=1_000_000, validation_alias="ADAPTIVE_ADMISSION_SOFT_MEM_MB"
    )
    # DB single-statement write p95 and pool checkout wait p95 (30 s window,
    # at least 20 samples) above these shrink the budget.
    adaptive_admission_db_write_p95_ms: float = Field(
        default=500.0, gt=0, le=600_000, validation_alias="ADAPTIVE_ADMISSION_DB_WRITE_P95_MS"
    )
    adaptive_admission_pool_wait_p95_ms: float = Field(
        default=500.0, gt=0, le=600_000, validation_alias="ADAPTIVE_ADMISSION_POOL_WAIT_P95_MS"
    )
    # Fast brake (#141 follow-up, 2026-10-18): load1 is a one-minute average,
    # so a burst of turns saturated the 2 vCPU host before load said so.
    # These faster signals are checked on every sample (1 s), not every adjust:
    # a 10 s DB write p95 or pool-wait p95, the write statements running now,
    # or host CPU busy (/proc/stat) for N samples in a row. A brake halves the
    # budget (once per cooldown) and clamps it to what is already in flight,
    # so nothing new starts until a turn finishes; growth waits while any
    # brake signal is bad. 0 turns a signal off.
    adaptive_admission_brake_db_write_p95_ms: float = Field(
        default=800.0, ge=0, le=600_000, validation_alias="ADAPTIVE_ADMISSION_BRAKE_DB_WRITE_P95_MS"
    )
    adaptive_admission_brake_pool_wait_p95_ms: float = Field(
        default=250.0,
        ge=0,
        le=600_000,
        validation_alias="ADAPTIVE_ADMISSION_BRAKE_POOL_WAIT_P95_MS",
    )
    adaptive_admission_brake_writes_in_flight: int = Field(
        default=10, ge=0, le=10_000, validation_alias="ADAPTIVE_ADMISSION_BRAKE_WRITES_IN_FLIGHT"
    )
    adaptive_admission_brake_cpu_ratio: float = Field(
        default=0.95, ge=0, le=1, validation_alias="ADAPTIVE_ADMISSION_BRAKE_CPU_RATIO"
    )
    adaptive_admission_brake_cpu_samples: int = Field(
        default=3, ge=1, le=600, validation_alias="ADAPTIVE_ADMISSION_BRAKE_CPU_SAMPLES"
    )
    # Load average counts tasks waiting on disk and work from other
    # containers on the host, and lags a minute behind. A high load trips the
    # danger latch, shrinks or holds the budget only while host CPU busy
    # (smoothed over ~5 s) is at least this ratio; with the CPU cool the latch
    # releases. 0 = load alone, as before. An unreadable CPU falls back to load.
    adaptive_admission_load_cpu_confirm_ratio: float = Field(
        default=0.8,
        ge=0,
        le=1,
        validation_alias="ADAPTIVE_ADMISSION_LOAD_CPU_CONFIRM_RATIO",
    )
    adaptive_admission_brake_cooldown_seconds: float = Field(
        default=5.0, ge=0, le=600, validation_alias="ADAPTIVE_ADMISSION_BRAKE_COOLDOWN_SECONDS"
    )
    # Hold band (no growth, no shrink): load in [hold, soft), MemAvailable in
    # [soft, hold) MiB, or the worker-thread pool at least this full.
    adaptive_admission_hold_load: float = Field(
        default=3.0, ge=0, le=10_000, validation_alias="ADAPTIVE_ADMISSION_HOLD_LOAD"
    )
    adaptive_admission_hold_mem_mb: int = Field(
        default=1100, ge=0, le=1_000_000, validation_alias="ADAPTIVE_ADMISSION_HOLD_MEM_MB"
    )
    # Of the 256-thread sync pool (main.ANYIO_THREAD_TOKENS): 0.45 holds at
    # ~115 borrowed threads, where 0.9 of the old 128-thread pool did. At 0.9
    # of 256 it would only trip once the 200-place queue was nearly full.
    adaptive_admission_hold_threadpool_ratio: float = Field(
        default=0.45, ge=0, le=1, validation_alias="ADAPTIVE_ADMISSION_HOLD_THREADPOOL_RATIO"
    )
    # Danger latch reserve / release (60-student rerun, 2026-10-19: a full
    # stop held 1400 s at in-flight 0 while polling kept load at 4.7-5.9).
    # Load danger still admits this many top-level operations per process,
    # Scorer/Summarizer finishing first, then student turns (0 = old full
    # stop; memory danger always stops fully). A latch held this long while
    # load is under the trip line is released (0 = only load <= resume).
    # After a release, top-level admissions ramp from the reserve by `step`
    # every `ramp` seconds up to the in-flight cap (0 = no ramp).
    adaptive_admission_danger_reserve_slots: int = Field(
        default=2, ge=0, le=64, validation_alias="ADAPTIVE_ADMISSION_DANGER_RESERVE_SLOTS"
    )
    # Memory danger: still admit one operation while nothing runs (0 = full
    # stop), so a long low-memory spell cannot strand queued students.
    adaptive_admission_memory_danger_trickle: int = Field(
        default=1, ge=0, le=1, validation_alias="ADAPTIVE_ADMISSION_MEMORY_DANGER_TRICKLE"
    )
    adaptive_admission_danger_max_hold_seconds: float = Field(
        default=120.0,
        ge=0,
        le=86_400,
        validation_alias="ADAPTIVE_ADMISSION_DANGER_MAX_HOLD_SECONDS",
    )
    adaptive_admission_release_ramp_seconds: float = Field(
        default=5.0, ge=0, le=600, validation_alias="ADAPTIVE_ADMISSION_RELEASE_RAMP_SECONDS"
    )
    adaptive_admission_release_ramp_step: int = Field(
        default=1, ge=1, le=1_000, validation_alias="ADAPTIVE_ADMISSION_RELEASE_RAMP_STEP"
    )
    # GET /conversations/{id} while admission sheds load (danger, ramp or a
    # fast brake): serve a copy at most this old per (user, conversation,
    # revision) and tell clients to poll no faster (X-Maya-Poll-After). 0 off.
    conversation_poll_pressure_cache_seconds: float = Field(
        default=5.0,
        ge=0,
        le=60,
        validation_alias="CONVERSATION_POLL_PRESSURE_CACHE_SECONDS",
    )
    # Layer-1 queue depth; past it callers get an immediate retryable 503.
    adaptive_admission_queue_max: int = Field(
        default=200, ge=0, le=10_000, validation_alias="ADAPTIVE_ADMISSION_QUEUE_MAX"
    )
    adaptive_admission_wait_seconds: int = Field(
        default=180, ge=0, le=3_600, validation_alias="ADAPTIVE_ADMISSION_WAIT_SECONDS"
    )
    adaptive_admission_retry_seconds: int = Field(
        default=5, ge=1, le=300, validation_alias="ADAPTIVE_ADMISSION_RETRY_SECONDS"
    )
    adaptive_admission_weight_llm: int = Field(
        default=4, ge=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_WEIGHT_LLM"
    )
    adaptive_admission_weight_create: int = Field(
        default=3, ge=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_WEIGHT_CREATE"
    )
    adaptive_admission_weight_write: int = Field(
        default=2, ge=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_WEIGHT_WRITE"
    )
    adaptive_admission_weight_login: int = Field(
        default=1, ge=0, le=1_000, validation_alias="ADAPTIVE_ADMISSION_WEIGHT_LOGIN"
    )
    # This is safe only when the application is reachable through the isolated
    # production Caddy network and that gateway overwrites X-Forwarded-For.
    auth_trust_gateway_x_forwarded_for: bool = Field(
        default=False, validation_alias="AUTH_TRUST_GATEWAY_X_FORWARDED_FOR"
    )

    @field_validator("database_url")
    @classmethod
    def database_is_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql"):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL; SQLite is no longer supported."
            )
        return value

    @field_validator("session_secret", mode="before")
    @classmethod
    def empty_secret_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("classroom_public_base_url", mode="before")
    @classmethod
    def classroom_public_url_is_origin(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("CLASSROOM_PUBLIC_BASE_URL must be an HTTP origin")
        if value != value.strip() or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("CLASSROOM_PUBLIC_BASE_URL must not contain whitespace controls")
        if "?" in value or "#" in value:
            raise ValueError(
                "CLASSROOM_PUBLIC_BASE_URL must not contain query or fragment delimiters"
            )
        candidate = value
        parsed = urlsplit(candidate)
        if parsed.path == "/" and not parsed.query and not parsed.fragment:
            candidate = candidate[:-1]
            parsed = urlsplit(candidate)
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("CLASSROOM_PUBLIC_BASE_URL has an invalid port") from None
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
            or "@" in parsed.netloc
            or "\\" in parsed.netloc
        ):
            raise ValueError(
                "CLASSROOM_PUBLIC_BASE_URL must be an absolute HTTP origin without a path"
            )
        return f"{parsed.scheme.lower()}://{parsed.netloc}"

    @field_validator("demo_mode", mode="before")
    @classmethod
    def empty_demo_mode_is_false(cls, value: object) -> object:
        # docker-compose forwards an empty value when DEMO_MODE is not set.
        # Treat that as the secure disabled default instead of a settings
        # parse failure.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator("demo_quick_login", mode="before")
    @classmethod
    def empty_demo_quick_login_is_false(cls, value: object) -> object:
        # Compose forwards an empty value when DEMO_QUICK_LOGIN is unset.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "debate_llm_model",
        "debate_llm_temperature",
        "debate_llm_top_p",
        "debate_llm_presence_penalty",
        "debate_llm_frequency_penalty",
        "debate_llm_repetition_penalty",
        "debate_llm_max_tokens",
        "debate_llm_seed",
        "debate_tts_model",
        "debate_tts_rate",
        "debate_tts_instruction",
        "debate_tts_seed",
        mode="before",
    )
    @classmethod
    def empty_debate_value_is_unset(cls, value: object) -> object:
        # Compose forwards an empty value for ${VAR:-}; empty means not sent.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("debate_llm_model")
    @classmethod
    def debate_llm_model_is_an_explicit_id(cls, value: object) -> object:
        if value is not None and (
            not isinstance(value, str) or _LLM_MODEL_RE.fullmatch(value.strip()) is None
        ):
            raise ValueError("DEBATE_LLM_MODEL must be a model id")
        return value.strip() if isinstance(value, str) else value

    @field_validator("voice_clone_model", mode="before")
    @classmethod
    def empty_voice_clone_model_is_default(cls, value: object) -> object:
        # Compose forwards an empty value when VOICE_CLONE_MODEL is unset.
        return "qwen-audio-3.1-tts-flash" if isinstance(value, str) and not value.strip() else value

    @field_validator("allow_legacy_demo_users", mode="before")
    @classmethod
    def empty_legacy_demo_users_is_false(cls, value: object) -> object:
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "llm_provider",
        "report_provider",
        "embedding_provider",
        "tts_provider",
        "voice_provider",
        mode="before",
    )
    @classmethod
    def empty_provider_is_mock(cls, value: object) -> object:
        return "mock" if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "llm_provider",
        "report_provider",
        "embedding_provider",
        "tts_provider",
        "voice_provider",
    )
    @classmethod
    def provider_selector_is_supported(cls, value: str) -> str:
        if value not in {"mock", "dashscope"}:
            raise ValueError("provider selector must be mock or dashscope")
        return value

    @field_validator("fallback_voice_profile_id")
    @classmethod
    def fallback_id_is_uuid(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            UUID(value)
        except ValueError:
            raise ValueError("FALLBACK_VOICE_PROFILE_ID must be a UUID") from None
        return value

    @field_validator("provider_policy_hash", mode="before")
    @classmethod
    def provider_policy_hash_is_explicit_sha256(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value.strip()) is None:
            raise ValueError("PROVIDER_POLICY_HASH must be a lowercase SHA-256 value")
        return value.strip()

    @field_validator("llm_model", mode="before")
    @classmethod
    def llm_model_is_an_explicit_id(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_LLM_MODEL
        if not isinstance(value, str) or _LLM_MODEL_RE.fullmatch(value.strip()) is None:
            raise ValueError("LLM_MODEL must be a model id")
        return value.strip()

    @field_validator(
        "embedding_provider_policy_hash",
        "llm_provider_policy_hash",
        "report_provider_policy_hash",
        mode="before",
    )
    @classmethod
    def provider_slice_policy_hash_is_explicit_sha256(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value.strip()) is None:
            raise ValueError("provider slice policy hash must be a lowercase SHA-256 value")
        return value.strip()

    @property
    def session_ttl(self) -> timedelta:
        """Return the configured session lifetime."""

        return timedelta(days=self.session_ttl_days)

    @property
    def is_test(self) -> bool:
        """Whether ephemeral test-only defaults may be used."""

        if self.is_production:
            return False
        explicit = self.maya_env.strip().lower()
        if explicit in {"test", "testing"}:
            return True
        # pytest sets this variable while running a test. It makes a directly
        # constructed TestClient safe without changing a developer's shell.
        return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("MAYA_TESTING") == "1"

    @property
    def is_production(self) -> bool:
        """Treat either production environment marker as a hard production gate."""

        return (
            self.node_env.strip().lower() == "production"
            or self.maya_env.strip().lower() == "production"
        )

    @field_validator("capacity_scale", mode="before")
    @classmethod
    def capacity_scale_blank_is_unset(cls, value: object) -> object:
        # docker-compose forwards CAPACITY_SCALE as "" when it is not set.
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def scale_capacity_with_host(self) -> Settings:
        from app.core.capacity import SCALED_CAPS, SCALED_LOADS, capacity_scale, scaled_values

        scale = capacity_scale(
            baseline_cpus=self.capacity_baseline_cpus, override=self.capacity_scale
        )
        # Validators run once per construction; copies (model_copy) keep the
        # already scaled values, so nothing is multiplied twice.
        names = SCALED_LOADS + SCALED_CAPS
        for name, value in scaled_values({n: getattr(self, n) for n in names}, scale).items():
            object.__setattr__(self, name, value)
        return self

    def validate_runtime(self) -> None:
        """Reject insecure production configuration at application startup."""

        if self.is_production:
            if self.demo_mode or self.demo_quick_login or self.demo_auto_confirm_provider:
                raise RuntimeError(
                    "Production requires DEMO_MODE, DEMO_QUICK_LOGIN and "
                    "DEMO_AUTO_CONFIRM_PROVIDER to be false"
                )
            if not self._has_public_https_origin():
                raise RuntimeError(
                    "Production requires CLASSROOM_PUBLIC_BASE_URL to be an HTTPS DNS origin"
                )
        if self.session_secret is None or len(self.session_secret.encode("utf-8")) < 32:
            if self.is_production or not self.is_test:
                raise RuntimeError("SESSION_SECRET must contain at least 32 bytes")
        self.validate_provider_configuration()
        # A bad baseline-voice map must stop startup rather than bind the
        # wrong character at the first chat.
        self.parsed_baseline_default_voices()
        # Parse the complete private graph before the application lifespan
        # yields. A malformed catalog therefore prevents readiness rather
        # than partially applying identities.
        production_default_catalog = self.is_production and self.uses_demo_default_accounts_file
        if (
            self.demo_mode
            or self.demo_quick_login
            or (self.resolved_demo_accounts_file.exists() and not production_default_catalog)
        ):
            from app.modules.auth.credentials import prepare_catalog

            prepare_catalog(self)

    def parsed_baseline_default_voices(self) -> dict[str, str]:
        """Return ``character -> voice profile id`` or raise on a bad map."""

        raw = self.baseline_default_voices
        if raw is None or not str(raw).strip():
            return {}
        found: dict[str, str] = {}
        allowed = {"socrates", "plato", "laozi"}
        for part in str(raw).split(","):
            item = part.strip()
            if not item or "=" not in item:
                raise RuntimeError("BASELINE_DEFAULT_VOICES entries are name=voice_profile_id")
            name, profile_id = (piece.strip() for piece in item.split("=", 1))
            name = name.lower()
            if name not in allowed or name in found or not profile_id:
                raise RuntimeError(
                    "BASELINE_DEFAULT_VOICES has an unknown, empty, or repeated character"
                )
            try:
                parsed = UUID(profile_id)
            except ValueError as exc:
                raise RuntimeError(
                    "BASELINE_DEFAULT_VOICES voice profile id must be a UUID"
                ) from exc
            found[name] = str(parsed)
        return found

    def validate_provider_configuration(self) -> None:
        """Allow Mock, reviewed text slices, and speech on one DashScope key.

        LLM, Embedding and Report keep their composition and policy-hash
        rules.  TTS and Voice may be ``dashscope`` beside any allowed core,
        including on their own, only through the same ``DASHSCOPE_API_KEY``.
        There is no second speech key.  Selector construction performs no
        network I/O.  The LLM adapter still requires its own runtime
        confirmation before any request.
        """

        selectors = (
            self.llm_provider,
            self.report_provider,
            self.embedding_provider,
            self.tts_provider,
            self.voice_provider,
        )
        if any(value not in {"mock", "dashscope"} for value in selectors):
            raise RuntimeError("provider selector is not supported")

        # Speech is excluded from this tuple on purpose: adding it must not
        # change the dual-hash rule, which keys off a core of length two.
        core_names = tuple(
            name
            for name, value in (
                ("LLM_PROVIDER", self.llm_provider),
                ("REPORT_PROVIDER", self.report_provider),
                ("EMBEDDING_PROVIDER", self.embedding_provider),
            )
            if value == "dashscope"
        )
        speech_names = tuple(
            name
            for name, value in (
                ("TTS_PROVIDER", self.tts_provider),
                ("VOICE_PROVIDER", self.voice_provider),
            )
            if value == "dashscope"
        )
        allowed_cores = {
            (),
            ("EMBEDDING_PROVIDER",),
            ("LLM_PROVIDER",),
            ("LLM_PROVIDER", "EMBEDDING_PROVIDER"),
            ("REPORT_PROVIDER",),
            ("LLM_PROVIDER", "REPORT_PROVIDER"),
            ("REPORT_PROVIDER", "EMBEDDING_PROVIDER"),
            ("LLM_PROVIDER", "REPORT_PROVIDER", "EMBEDDING_PROVIDER"),
        }
        if core_names not in allowed_cores:
            raise RuntimeError(
                "runtime provider gate permits only the Real Embedding + Real LLM pair "
                "or one reviewed DashScope slice with Mock companions"
            )
        if core_names or speech_names:
            if not self.dashscope_api_key or not self.dashscope_api_key.strip():
                raise RuntimeError(
                    "DASHSCOPE_API_KEY is required for real Provider work; "
                    "Mock companions remain the default"
                )
            if not self.dashscope_workspace_id or not self.dashscope_workspace_id.strip():
                raise RuntimeError(
                    "DASHSCOPE_WORKSPACE_ID is required for real Provider work; "
                    "Mock companions remain the default"
                )
            if self.dashscope_region != "cn-beijing":
                raise RuntimeError(
                    "DASHSCOPE_REGION must be cn-beijing for real Provider work; "
                    "Mock companions remain the default"
                )
        # A legacy PROVIDER_POLICY_HASH is endpoint-ambiguous when both real
        # slices are selected.  Require the two explicit fields in that case;
        # a single-real configuration may still use the old field.
        if set(core_names) == {"LLM_PROVIDER", "EMBEDDING_PROVIDER"}:
            if self.provider_policy_hash is not None and not (
                self.embedding_provider_policy_hash is not None
                and self.llm_provider_policy_hash is not None
            ):
                raise RuntimeError(
                    "dual real Provider work requires separate "
                    "EMBEDDING_PROVIDER_POLICY_HASH and LLM_PROVIDER_POLICY_HASH"
                )
            if self.embedding_provider_policy_hash is None:
                raise RuntimeError(
                    "EMBEDDING_PROVIDER_POLICY_HASH is required for real Embedding publication"
                )
            if self.llm_provider_policy_hash is None:
                raise RuntimeError("LLM_PROVIDER_POLICY_HASH is required for real LLM publication")
        elif self.embedding_provider == "dashscope" and self.embedding_policy_hash is None:
            raise RuntimeError(
                "EMBEDDING_PROVIDER_POLICY_HASH (or an unambiguous legacy "
                "PROVIDER_POLICY_HASH) is required for real Embedding publication"
            )
        elif self.llm_provider == "dashscope" and self.llm_policy_hash is None:
            raise RuntimeError(
                "LLM_PROVIDER_POLICY_HASH (or an unambiguous legacy "
                "PROVIDER_POLICY_HASH) is required for real LLM publication"
            )
        if self.report_provider == "dashscope" and self.report_policy_hash is None:
            raise RuntimeError(
                "REPORT_PROVIDER_POLICY_HASH is required for real Maya Report publication"
            )

    @property
    def embedding_policy_hash(self) -> str | None:
        """Return the hash bound to real Embedding, with legacy compatibility."""

        if self.embedding_provider_policy_hash is not None:
            return self.embedding_provider_policy_hash
        if self.provider_policy_hash is not None and self.embedding_provider == "dashscope":
            if self.llm_provider != "dashscope":
                return self.provider_policy_hash
        return None

    @property
    def llm_policy_hash(self) -> str | None:
        """Return the hash bound to real LLM, with legacy compatibility."""

        if self.llm_provider_policy_hash is not None:
            return self.llm_provider_policy_hash
        if self.provider_policy_hash is not None and self.llm_provider == "dashscope":
            if self.embedding_provider != "dashscope":
                return self.provider_policy_hash
        return None

    @property
    def report_policy_hash(self) -> str | None:
        """Return the endpoint policy hash bound to Real Maya Report."""

        if self.report_provider_policy_hash is not None:
            return self.report_provider_policy_hash
        if self.provider_policy_hash is not None and self.report_provider == "dashscope":
            if self.llm_provider != "dashscope" and self.embedding_provider != "dashscope":
                return self.provider_policy_hash
        return None

    def chat_settings(self) -> Settings:
        """These settings with the Chatform key in place of the shared one."""

        key = (self.dashscope_chat_api_key or "").strip()
        if not key:
            return self
        return self.model_copy(update={"dashscope_api_key": key})

    def provider_policy_hash_for(self, slice_name: str) -> str | None:
        """Resolve an endpoint policy hash without silently crossing slices."""

        if slice_name == "embedding":
            return self.embedding_policy_hash
        if slice_name == "llm":
            return self.llm_policy_hash
        if slice_name == "report":
            return self.report_policy_hash
        raise ValueError("provider policy slice must be embedding, llm or report")

    @property
    def secret_bytes(self) -> bytes:
        """Return the signing key, using an ephemeral test key only in tests."""

        if self.session_secret is not None and len(self.session_secret.encode("utf-8")) >= 32:
            return self.session_secret.encode("utf-8")
        if self.is_test and not self.is_production:
            return b"maya-wave0-test-session-secret-not-for-production"
        # Keep a clear failure even if a caller uses the property before the
        # lifespan validator.
        raise RuntimeError("SESSION_SECRET must contain at least 32 bytes")

    @property
    def classroom_public_origin(self) -> str | None:
        """Return a valid QR origin: the public HTTPS origin or local Demo URL.

        Loopback is valid for the ordinary local site but cannot be placed in
        a QR code: a phone would resolve it to itself. Demo keeps its existing
        private numeric and ``.local`` behavior; production uses its exact
        configured public HTTPS DNS origin.
        """

        value = self.classroom_public_base_url
        if value is None:
            return None
        from app.core.origin import origin_tuple

        parsed_origin = origin_tuple(value)
        if parsed_origin is None:
            return None
        scheme, hostname, _port = parsed_origin
        hostname = hostname.rstrip(".")
        if self.is_production:
            return value if scheme == "https" and self._is_public_dns_hostname(hostname) else None
        if hostname == "localhost":
            return None
        try:
            address = ip_address(hostname)
        except ValueError:
            return value if hostname.endswith(".local") else None
        private_networks = (
            ip_network("10.0.0.0/8"),
            ip_network("172.16.0.0/12"),
            ip_network("192.168.0.0/16"),
            ip_network("fc00::/7"),
        )
        return value if any(address in network for network in private_networks) else None

    @staticmethod
    def _is_public_dns_hostname(hostname: str) -> bool:
        """Check public DNS hostname syntax without making a DNS request."""

        lowered = hostname.lower().rstrip(".")
        if lowered.endswith((".local", ".localhost")) or lowered in {"localhost", "local"}:
            return False
        try:
            ip_address(lowered)
        except ValueError:
            return bool(_PUBLIC_DNS_HOST_RE.fullmatch(lowered))
        return False

    def _has_public_https_origin(self) -> bool:
        value = self.classroom_public_base_url
        if value is None:
            return False
        from app.core.origin import origin_tuple

        parsed_origin = origin_tuple(value)
        if parsed_origin is None:
            return False
        scheme, hostname, _port = parsed_origin
        return scheme == "https" and self._is_public_dns_hostname(hostname)

    @property
    def resolved_data_root(self) -> Path:
        path = self.data_root
        if not path.is_absolute():
            # Resolve against the backend package directory when launched from
            # another working directory (for example by a process manager).
            path = Path(__file__).resolve().parents[2] / path
        return path

    @property
    def resolved_demo_users_file(self) -> Path:
        path = self.demo_users_file
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    @property
    def resolved_demo_accounts_file(self) -> Path:
        path = self.demo_accounts_file
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    @property
    def uses_demo_default_accounts_file(self) -> bool:
        """Whether the configured credential path is the repository Demo catalog."""

        default_path = (
            Path(__file__).resolve().parents[2] / "config/demo-accounts/accounts.private.md"
        )
        return self.resolved_demo_accounts_file.resolve() == default_path.resolve()

    @property
    def production_account_catalog_available(self) -> bool:
        """Whether production has a separate, present private account catalog."""

        return (
            self.is_production
            and not self.uses_demo_default_accounts_file
            and self.resolved_demo_accounts_file.is_file()
        )

    @property
    def resolved_config_root(self) -> Path:
        """Where private operator files live, outside the disposable runtime.

        Derived from the accounts file so a container mounting ``/app/config``
        and a host checkout both resolve to the same directory.
        """

        return self.resolved_demo_accounts_file.parent.parent

    def ensure_data_root(self) -> None:
        root = self.resolved_data_root
        root.mkdir(parents=True, exist_ok=True)
        # The Demo data root is private application state.  Apply the mode on
        # every startup so a copied directory cannot silently retain broad
        # permissions from a previous run.
        root.chmod(0o700)
        for relative in ("groups", "snapshots", "tmp", "tmp/publish", "private"):
            child = root / relative
            child.mkdir(parents=True, exist_ok=True)
            child.chmod(0o700)

    def cookie_secure(self, request_scheme: str | None = None) -> bool:
        """Use Secure cookies only when the active origin is HTTPS.

        The local Demo is intentionally served over HTTP by Caddy, so using a
        blanket production flag would make the browser drop the session.  A
        configured HTTPS classroom URL or an HTTPS request opts in securely.
        """

        if request_scheme and request_scheme.lower() == "https":
            return True
        if self.classroom_public_base_url:
            return urlsplit(self.classroom_public_base_url).scheme.lower() == "https"
        return False

    def ephemeral_test_secret(self) -> str:
        """Create a one-off secret for callers constructing test settings.

        This helper is intentionally explicit and never called for a normal
        process.  It is useful to tests that want independent app instances.
        """

        if not self.is_test:
            raise RuntimeError("ephemeral secrets are available only in test mode")
        return secrets.token_urlsafe(32)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configured_llm_model() -> str:
    """Chat and report model. Debates use ``configured_debate_llm_model``."""

    return get_settings().llm_model


def configured_debate_llm_model() -> str:
    """The Debate turn model: DEBATE_LLM_MODEL, else the shared LLM_MODEL."""

    settings = get_settings()
    return settings.debate_llm_model or settings.llm_model
