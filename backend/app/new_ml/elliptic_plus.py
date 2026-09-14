"""Fresh, research-only Elliptic++ ingestion with explicit provenance limits."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import pandas as pd


SOURCE_URI = "https://drive.google.com/drive/folders/1MRPXz79Lu_JGLlJ21MDfML44dKN9R08l"
PUBLISHER_REPOSITORY = "https://github.com/git-disl/EllipticPlusPlus"
FEATURE_SCHEMA_VERSION = "elliptic-plus-transaction-public-v1"
TRANSACTION_FEATURES = (
    "in_txs_degree", "out_txs_degree", "total_BTC", "fees", "size",
    "num_input_addresses", "num_output_addresses", "in_BTC_min", "in_BTC_max",
    "in_BTC_mean", "in_BTC_median", "in_BTC_total", "out_BTC_min",
    "out_BTC_max", "out_BTC_mean", "out_BTC_median", "out_BTC_total",
)
REQUIRED_FILES = ("txs_features.csv", "txs_classes.csv", "txs_edgelist.csv")
WALLET_FEATURE_SCHEMA_VERSION = "elliptic-plus-wallet-public-v1"
WALLET_FILE = "wallets_features_classes_combined.csv"
WALLET_FEATURES = (
    "num_txs_as_sender", "num_txs_as receiver", "first_block_appeared_in",
    "last_block_appeared_in", "lifetime_in_blocks", "total_txs", "first_sent_block",
    "first_received_block", "num_timesteps_appeared_in", "btc_transacted_total",
    "btc_transacted_min", "btc_transacted_max", "btc_transacted_mean",
    "btc_transacted_median", "btc_sent_total", "btc_sent_min", "btc_sent_max",
    "btc_sent_mean", "btc_sent_median", "btc_received_total", "btc_received_min",
    "btc_received_max", "btc_received_mean", "btc_received_median", "fees_total",
    "fees_min", "fees_max", "fees_mean", "fees_median", "fees_as_share_total",
    "fees_as_share_min", "fees_as_share_max", "fees_as_share_mean",
    "fees_as_share_median", "blocks_btwn_txs_total", "blocks_btwn_txs_min",
    "blocks_btwn_txs_max", "blocks_btwn_txs_mean", "blocks_btwn_txs_median",
    "blocks_btwn_input_txs_total", "blocks_btwn_input_txs_min",
    "blocks_btwn_input_txs_max", "blocks_btwn_input_txs_mean",
    "blocks_btwn_input_txs_median", "blocks_btwn_output_txs_total",
    "blocks_btwn_output_txs_min", "blocks_btwn_output_txs_max",
    "blocks_btwn_output_txs_mean", "blocks_btwn_output_txs_median",
    "num_addr_transacted_multiple", "transacted_w_address_total",
    "transacted_w_address_min", "transacted_w_address_max",
    "transacted_w_address_mean", "transacted_w_address_median",
)
CLASS_MAP = {1: 1, 2: 0, 3: None}

# Frozen before metrics are observed. Steps 26, 33, and 40 are purge boundaries.
SPLIT_STEPS = {
    "train": tuple(range(1, 26)),
    "validation": tuple(range(27, 33)),
    "calibration": tuple(range(34, 40)),
    "test": tuple(range(41, 50)),
}
PURGED_STEPS = (26, 33, 40)


@dataclass(frozen=True)
class EllipticPlusDataset:
    frame: pd.DataFrame
    file_hashes: dict[str, str]
    snapshot_hash: str
    audit: dict


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_hash(file_hashes: dict[str, str]) -> str:
    material = "\n".join(f"{name}:{file_hashes[name]}" for name in sorted(file_hashes))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def inspect_source(data_dir: Path, required_files: tuple[str, ...] = REQUIRED_FILES) -> dict:
    missing = [name for name in required_files if not (data_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Elliptic++ source is incomplete: {', '.join(missing)}")
    hashes = {name: sha256_file(data_dir / name) for name in required_files}
    return {
        "source_uri": SOURCE_URI,
        "publisher_repository": PUBLISHER_REPOSITORY,
        "source_kind": "public_research",
        "owner": "Youssef Elmougy and Ling Liu, Georgia Institute of Technology",
        "license_name": "not stated in publisher repository; legal review required",
        "permitted_purpose": "exploratory research and shadow evaluation only",
        "independently_acquired": True,
        "content_hashes": hashes,
        "snapshot_hash": _snapshot_hash(hashes),
        "quality_limits": [
            "BTC only",
            "publisher labels are not locally dual-reviewed",
            "ordinal time steps are not exact event timestamps",
            "license is not stated in the publisher repository",
            "anonymous original Elliptic features are excluded",
            "retrospective research only; no production promotion",
        ],
    }


def load_transaction_dataset(data_dir: Path) -> EllipticPlusDataset:
    manifest = inspect_source(data_dir)
    feature_columns = ["txId", "Time step", *TRANSACTION_FEATURES]
    features = pd.read_csv(data_dir / "txs_features.csv", usecols=feature_columns)
    labels = pd.read_csv(data_dir / "txs_classes.csv", usecols=["txId", "class"])
    if features["txId"].duplicated().any() or labels["txId"].duplicated().any():
        raise ValueError("Elliptic++ transaction identifiers must be unique")
    frame = features.merge(labels, on="txId", how="inner", validate="one_to_one")
    frame["target"] = frame["class"].map(CLASS_MAP)
    unknown_count = int(frame["target"].isna().sum())
    frame = frame.loc[frame["target"].notna()].copy()
    frame["target"] = frame["target"].astype("int8")
    frame["time_step"] = frame["Time step"].astype("int16")
    frame["group_key"] = frame["time_step"].map(lambda value: f"elliptic-component-step-{value:02d}")
    frame["sample_id"] = frame["txId"].astype(str).map(
        lambda value: hashlib.sha256(f"{manifest['snapshot_hash']}:{value}".encode()).hexdigest()
    )
    split_by_step = {step: split for split, steps in SPLIT_STEPS.items() for step in steps}
    frame["split"] = frame["time_step"].map(split_by_step)
    purged_count = int(frame["split"].isna().sum())
    frame = frame.loc[frame["split"].notna()].reset_index(drop=True)
    split_groups = frame.groupby("group_key")["split"].nunique()
    if int(split_groups.max()) != 1:
        raise ValueError("A graph component group crosses frozen split boundaries")
    audit = {
        "rows_with_known_labels": int(len(frame)),
        "unknown_labels_excluded": unknown_count,
        "purge_steps": list(PURGED_STEPS),
        "purged_known_rows": purged_count,
        "split_steps": {key: list(value) for key, value in SPLIT_STEPS.items()},
        "class_counts": {
            split: {str(int(label)): int(count) for label, count in subset["target"].value_counts().items()}
            for split, subset in frame.groupby("split", observed=True)
        },
        "feature_columns": list(TRANSACTION_FEATURES),
        "feature_policy": "Only the 17 publisher-named transaction fields are used; anonymous local/aggregate fields are excluded.",
        "group_policy": "Each time step is an isolated transaction-graph component and belongs to exactly one split.",
    }
    return EllipticPlusDataset(frame=frame, file_hashes=manifest["content_hashes"],
                               snapshot_hash=manifest["snapshot_hash"], audit=audit)


def load_wallet_dataset(data_dir: Path) -> EllipticPlusDataset:
    manifest = inspect_source(data_dir, (WALLET_FILE,))
    columns = ["address", "Time step", "class", *WALLET_FEATURES]
    # Float32 keeps the public 600 MB source workable on a prototype laptop;
    # these are research features rather than monetary ledger values.
    dtypes = {"Time step": "int16", "class": "int8"}
    dtypes.update({name: "float32" for name in WALLET_FEATURES})
    frame = pd.read_csv(data_dir / WALLET_FILE, usecols=columns, dtype=dtypes)
    frame["target"] = frame["class"].map(CLASS_MAP)
    unknown_count = int(frame.loc[frame["target"].isna(), "address"].nunique())
    frame = frame.loc[frame["target"].notna()].copy()
    frame["target"] = frame["target"].astype("int8")
    frame["time_step"] = frame["Time step"].astype("int16")
    conflicting = frame.groupby("address")["target"].nunique()
    conflicting_addresses = set(conflicting.loc[conflicting > 1].index)
    frame = frame.loc[~frame["address"].isin(conflicting_addresses)]
    frame = frame.sort_values(["address", "time_step"]).drop_duplicates("address", keep="last")
    frame["group_key"] = frame["address"].map(
        lambda value: hashlib.sha256(f"group:{manifest['snapshot_hash']}:{value}".encode()).hexdigest()
    )
    frame["sample_id"] = frame["address"].map(
        lambda value: hashlib.sha256(f"sample:{manifest['snapshot_hash']}:{value}".encode()).hexdigest()
    )
    split_by_step = {step: split for split, steps in SPLIT_STEPS.items() for step in steps}
    frame["split"] = frame["time_step"].map(split_by_step)
    purged_count = int(frame["split"].isna().sum())
    frame = frame.loc[frame["split"].notna()].reset_index(drop=True)
    audit = {
        "rows_with_known_labels": int(len(frame)),
        "unknown_wallets_excluded": unknown_count,
        "conflicting_wallet_labels_excluded": len(conflicting_addresses),
        "purge_steps": list(PURGED_STEPS),
        "purged_known_rows": purged_count,
        "split_steps": {key: list(value) for key, value in SPLIT_STEPS.items()},
        "class_counts": {
            split: {str(int(label)): int(count) for label, count in subset["target"].value_counts().items()}
            for split, subset in frame.groupby("split", observed=True)
        },
        "feature_columns": list(WALLET_FEATURES),
        "feature_policy": "Publisher-named wallet history fields at each wallet's final observed time step.",
        "group_policy": "One final observation per public address; irreversible snapshot-scoped group IDs.",
    }
    return EllipticPlusDataset(frame=frame, file_hashes=manifest["content_hashes"],
                               snapshot_hash=manifest["snapshot_hash"], audit=audit)
