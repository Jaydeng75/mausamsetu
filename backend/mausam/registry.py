"""Checksum-pinned candidate review, activation, and auditable rollback."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .storage import atomic_write, file_lock, json_bytes, safe_id


def inspect_candidate(root, version):
    base = Path(root) / "models" / safe_id(version)
    manifest = json.loads((base / "manifest.json").read_text())
    for filename, key in [("model.json", "model_sha256"), ("evaluation.json", "evaluation_sha256")]:
        path = base / filename
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(key):
            raise ValueError("Candidate artifact checksum failed")
    model = json.loads((base / "model.json").read_text())
    report = json.loads((base / "evaluation.json").read_text())
    return manifest, model, report


def activate(root, version, actor, reason, scope="production"):
    if scope not in ("production", "demonstration") or len(reason.strip()) < 10 or not actor:
        raise ValueError("An actor, review reason, and valid scope are required")
    base = Path(root) / "models"
    with file_lock(base / ".registry.lock"):
        manifest, model, report = inspect_candidate(root, version)
        if scope == "production" and not (
            manifest.get("data_kind") == "forecast" and manifest.get("evaluation_passed") is True
            and report.get("eligible_for_production") is True):
            raise ValueError("Production activation requires approved real-data acceptance evidence")
        event = {"event_id": str(uuid.uuid4()), "version": version, "actor": actor,
                 "reason": reason, "scope": scope, "model_sha256": manifest["model_sha256"],
                 "evaluation_sha256": manifest["evaluation_sha256"],
                 "approved_at": datetime.now(timezone.utc).isoformat()}
        active = base / ("active.json" if scope == "production" else "demo-active.json")
        event["previous_version"] = json.loads(active.read_text())["version"] if active.exists() else None
        atomic_write(base / "events" / (event["event_id"]+".json"), json_bytes(event))
        atomic_write(base / "approvals" / (version+".json"), json_bytes(event))
        atomic_write(active, json_bytes(event))
        return event


def approved_model(root, version, data_kind):
    manifest, model, report = inspect_candidate(root, version)
    path = Path(root) / "models" / "approvals" / (safe_id(version)+".json")
    if not path.exists():
        raise ValueError("Candidate has not been reviewed and activated")
    approval = json.loads(path.read_text())
    if approval["model_sha256"] != manifest["model_sha256"] or approval["evaluation_sha256"] != manifest["evaluation_sha256"]:
        raise ValueError("Approved artifact was changed after review")
    if data_kind != manifest["data_kind"]:
        raise ValueError("Training and publication data kinds differ")
    if data_kind == "forecast" and approval["scope"] != "production":
        raise ValueError("Demonstration approval cannot authorize provider forecasts")
    return model, manifest, approval


def resolve_active(root, data_kind):
    name = 'demo-active.json' if data_kind == 'synthetic' else 'active.json'
    path = Path(root) / 'models' / name
    if not path.exists():
        raise ValueError('No approved active model for this data kind')
    event = json.loads(path.read_text())
    approved_model(root, event['version'], data_kind)
    return event
