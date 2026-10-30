"""Independent referee (privileged). The scout never imports this package."""
from logicscout.referee.referee import evaluate, report_digest, run_case

__all__ = ["evaluate", "report_digest", "run_case"]
