"""Wave 3 classroom interaction module.

The package owns the anonymous vote/barrage boundary and the one-way
interaction window lifecycle.  Report/insight generation is deliberately
injected through a small protocol so this module does not import M14 code.
"""

from .router import router
from .service import InsightEnqueuer, InteractionService

__all__ = ["InteractionService", "InsightEnqueuer", "router"]
