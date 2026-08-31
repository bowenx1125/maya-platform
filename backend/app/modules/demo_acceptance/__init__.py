"""Teacher-only, bounded Real-Core Demo acceptance-run ledger."""

from .service import (
    attach_acceptance_call,
    bind_acceptance_run_debate,
    bind_acceptance_run_report,
    create_acceptance_run,
    get_acceptance_run,
    summarize_acceptance_run,
)

__all__ = [
    "attach_acceptance_call",
    "bind_acceptance_run_debate",
    "bind_acceptance_run_report",
    "create_acceptance_run",
    "get_acceptance_run",
    "summarize_acceptance_run",
]
