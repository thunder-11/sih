"""Grouped chronological split manifests with cutoff and gap auditing."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta

from app.core.errors import ApplicationError
from app.new_ml.dataset import digest


@dataclass(frozen=True, slots=True)
class SplitSample:
    sample_id: str
    observed_at: object
    label_known_at: object
    group_key: str
    label: str


def grouped_chronological_split(samples: list[SplitSample], *, label_cutoff, purge_days: int = 0,
                                embargo_days: int = 0) -> dict:
    eligible = [item for item in samples if item.label in {"positive", "negative"} and item.label_known_at <= label_cutoff]
    groups = defaultdict(list)
    for item in eligible: groups[item.group_key].append(item)
    ordered = sorted(groups.items(), key=lambda pair: (max(item.observed_at for item in pair[1]), pair[0]))
    if len(ordered) < 4:
        raise ApplicationError(code="INSUFFICIENT_SPLIT_GROUPS", message="At least four eligible independent groups are required", status_code=422)
    count = len(ordered)
    train_end = min(max(1, int(count * .60)), count - 3)
    validation_end = min(max(train_end + 1, int(count * .75)), count - 2)
    calibration_end = min(max(validation_end + 1, int(count * .85)), count - 1)
    partitions = {"train": ordered[:train_end], "validation": ordered[train_end:validation_end],
                  "calibration": ordered[validation_end:calibration_end], "test": ordered[calibration_end:]}
    membership, excluded = {}, []
    boundary_times = [min(item.observed_at for _, values in partitions[name] for item in values)
                      for name in ("validation", "calibration", "test") if partitions[name]]
    purge, embargo = timedelta(days=purge_days), timedelta(days=embargo_days)
    for partition, grouped in partitions.items():
        for _, values in grouped:
            for item in values:
                near_boundary = any(boundary - purge <= item.observed_at < boundary + embargo for boundary in boundary_times)
                if near_boundary and (purge_days or embargo_days):
                    excluded.append({"sample_id": item.sample_id, "reason": "purge_or_embargo"})
                else:
                    membership[item.sample_id] = partition
    group_memberships = defaultdict(set)
    for item in eligible:
        if item.sample_id in membership: group_memberships[item.group_key].add(membership[item.sample_id])
    if any(len(value) > 1 for value in group_memberships.values()):
        raise AssertionError("group leakage detected")
    counts = {name: dict(Counter(item.label for item in eligible if membership.get(item.sample_id) == name))
              for name in partitions}
    audit = {"membership": membership, "excluded": excluded, "class_counts": counts,
             "rules": {"ordering": "group_max_observed_at", "groups_never_cross_splits": True,
                       "label_cutoff": label_cutoff.isoformat(), "purge_days": purge_days, "embargo_days": embargo_days},
             "manifest_hash": digest({"membership": membership, "excluded": excluded, "counts": counts})}
    return audit
