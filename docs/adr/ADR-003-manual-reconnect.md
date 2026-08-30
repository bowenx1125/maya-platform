# ADR-003: Manual-only network reconnect

Status: `ACCEPTED`

The classroom makes one automatic initial connection. A true network loss or sequence
gap preserves the authoritative view and exposes one teacher-triggered recovery
attempt. Timers, loops and background reconnects are forbidden. Terminal, superseded,
expired-login and Origin-mismatch causes are displayed distinctly and do not expose
Reconnect.
