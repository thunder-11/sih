"""Fresh ML data boundary.

This package is independently implemented from normalized non-ML evidence.  It
must never import legacy ML, NLP, feature, model, score, or explainer modules.
"""

from app.new_ml.contracts import LABEL_STATES, TASKS, TEMPORAL_MODES

__all__ = ["LABEL_STATES", "TASKS", "TEMPORAL_MODES"]
