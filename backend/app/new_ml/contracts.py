"""Stable Phase 7 task, label, and temporal contracts."""

TASKS = {
    "wallet_risk": {"unit": "network_qualified_wallet_snapshot", "target": "reviewed fraud-linked suspicious activity"},
    "transfer_risk": {"unit": "normalized_transfer_snapshot", "target": "reviewed fraud-linked transfer activity"},
    "pattern_multilabel": {"unit": "eligible_route_window_or_transfer", "target": "reviewed suspicious pattern classes"},
    "complaint_typology": {"unit": "locally_processed_redacted_complaint", "target": "seven typologies or unknown"},
}
LABEL_STATES = {"positive", "negative", "unknown", "disputed", "censored"}
TEMPORAL_MODES = {"report_baseline", "post_report", "retrospective_context"}
PATTERN_CLASSES = {"rapid_movement", "multi_hop", "splitting", "mixer", "bridge", "rapid_exchange_progression"}


def task_contracts() -> dict:
    return {"tasks": TASKS, "label_states": sorted(LABEL_STATES), "temporal_modes": sorted(TEMPORAL_MODES),
            "meaning": "Decision support for observed activity; never a criminality or future-crime determination."}
