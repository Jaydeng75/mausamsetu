"""Durable local publication. Locks require a shared POSIX filesystem, not S3."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def database(url):
    engine = create_engine(url, pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value) or ".." in value:
        raise ValueError("Invalid identifier")
    return value


def json_bytes(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()


def atomic_write(path, data):
    """Write, fsync, then replace; an interrupted write never exposes a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def file_lock(path, blocking=True):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(stream.fileno(), flags)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_time(manifest):
    sources = manifest.get("sources", [])
    value = (sources[0].get("initialization_time_utc") if sources else None)
    value = value or manifest.get("decision_time") or manifest.get("published_at")
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Run ordering requires timezone-aware timestamps")
    return parsed


class Archive:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_raw(self, data):
        digest = hashlib.sha256(data).hexdigest()
        path = self.root / "raw" / digest
        with file_lock(self.root / ".raw.lock"):
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("Corrupt content-addressed input")
            else:
                atomic_write(path, data)
        return digest, str(path)

    def _activate(self, manifest):
        current = self.latest()
        # Backfills remain inspectable but never replace a newer forecast cycle.
        if current is None or run_time(manifest) >= run_time(current):
            atomic_write(self.root / "latest.json", json_bytes({"run_id": manifest["run_id"]}))

    def publish(self, run_id, products, manifest):
        safe_id(run_id)
        base = self.root / "published"
        base.mkdir(exist_ok=True)
        target = base / run_id
        with file_lock(self.root / ".publication.lock"):
            if target.exists():
                existing = json.loads((target / "manifest.json").read_text())
                expected = {name: hashlib.sha256(data).hexdigest() for name, data in products.items()}
                if existing.get("input_hash") != manifest.get("input_hash") or existing.get("assets") != expected:
                    raise ValueError("Immutable run conflict")
                self.verify(run_id)
                if manifest.get("activate", True):
                    self._activate(existing)
                return existing
            stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=base))
            try:
                assets = {}
                for name, data in products.items():
                    if Path(name).name != name or name.startswith("."):
                        raise ValueError("Product names must be basenames")
                    atomic_write(stage / name, data)
                    assets[name] = hashlib.sha256(data).hexdigest()
                manifest = {**manifest, "run_id": run_id, "assets": assets}
                atomic_write(stage / "manifest.json", json_bytes(manifest))
                os.rename(stage, target)
                if manifest.get("activate", True):
                    self._activate(manifest)
                return manifest
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

    def verify(self, run_id):
        safe_id(run_id)
        base = self.root / "published" / run_id
        manifest = json.loads((base / "manifest.json").read_text())
        if manifest.get("run_id") != run_id:
            raise ValueError("Run identity mismatch")
        for name, digest in manifest.get("assets", {}).items():
            if Path(name).name != name or name.startswith("."):
                raise ValueError("Unsafe product path")
            path = base / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Published product checksum failed")
        return manifest

    def latest(self):
        path = self.root / "latest.json"
        if not path.exists():
            return None
        run_id = safe_id(json.loads(path.read_text())["run_id"])
        return json.loads((self.root / "published" / run_id / "manifest.json").read_text())
