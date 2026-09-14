"""Static independence audit for the fresh ML package."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORT_PREFIXES = ("services.risk_scoring", "services.tracer", "app.ml", "backend.ml", "ml")
FORBIDDEN_ARTIFACT_SUFFIXES = {".pkl", ".pickle", ".joblib", ".onnx", ".pt", ".pth", ".h5", ".keras"}


def _is_verified_fresh_artifact(path: Path, repository_root: Path) -> bool:
    artifact_root = repository_root / "artifacts" / "ml"
    try:
        path.relative_to(artifact_root)
    except ValueError:
        return False
    manifest_path = path.parent / "experiment.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest["artifact"]["sha256"]
    except (KeyError, TypeError, ValueError, OSError):
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == expected


def audit(package_root: Path, repository_root: Path) -> dict:
    import_violations = []
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    import_violations.append({"file": str(path.relative_to(repository_root)), "import": name})
    artifacts = [str(path.relative_to(repository_root)) for path in repository_root.rglob("*")
                 if path.is_file() and path.suffix.lower() in FORBIDDEN_ARTIFACT_SUFFIXES
                 and not _is_verified_fresh_artifact(path, repository_root)]
    return {"package": str(package_root.relative_to(repository_root)), "import_violations": import_violations,
            "legacy_model_artifacts": sorted(artifacts), "passed": not import_violations and not artifacts}
