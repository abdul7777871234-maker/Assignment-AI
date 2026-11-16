from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

TTL_SECONDS = 30 * 60
STORE_DIR = Path(os.environ.get("UAAI_UPLOAD_DIR", "/tmp/university-assignment-ai-uploads"))


class SecureUploadStore:
    """Encrypted-at-rest temporary upload store. Filenames are random IDs, not user names."""

    def __init__(self, key: str):
        try:
            key_bytes = key.encode("ascii")
            self.fernet = Fernet(key_bytes)
        except Exception as exc:
            raise ValueError("UPLOAD_ENCRYPTION_KEY must be a valid Fernet key.") from exc
        STORE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(STORE_DIR, 0o700)
        except OSError:
            pass

    def _path(self, file_id: str) -> Path:
        if not file_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in file_id):
            raise ValueError("Invalid file identifier.")
        return STORE_DIR / f"{file_id}.enc"

    def save(self, raw: bytes, original_name: str) -> dict:
        file_id = uuid.uuid4().hex
        encrypted = self.fernet.encrypt(raw)
        path = self._path(file_id)
        with open(path, "xb") as handle:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            handle.write(encrypted)
        now = time.time()
        return {
            "id": file_id,
            "name": Path(original_name).name[:180],
            "uploaded_at": now,
            "expires_at": now + TTL_SECONDS,
            "size": len(raw),
        }

    def read(self, file_id: str) -> bytes:
        path = self._path(file_id)
        if not path.exists():
            raise FileNotFoundError("This upload has expired or was deleted.")
        if time.time() - path.stat().st_mtime >= TTL_SECONDS:
            self.delete(file_id)
            raise FileNotFoundError("This upload has expired or was deleted.")
        try:
            return self.fernet.decrypt(path.read_bytes())
        except InvalidToken as exc:
            self.delete(file_id)
            raise ValueError("The encrypted upload could not be verified.") from exc

    def delete(self, file_id: str) -> None:
        path = self._path(file_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup_expired(self) -> int:
        STORE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        cutoff = time.time() - TTL_SECONDS
        removed = 0
        for path in STORE_DIR.glob("*.enc"):
            try:
                if path.stat().st_mtime <= cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def delete_all(self) -> None:
        for path in STORE_DIR.glob("*.enc"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


def start_cleanup_scheduler(store: SecureUploadStore) -> None:
    """Start one in-process cleanup worker. Also run cleanup on every app rerun."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = getattr(start_cleanup_scheduler, "_scheduler", None)
        if scheduler is None:
            scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
            scheduler.add_job(store.cleanup_expired, "interval", seconds=60,
                              id="upload_ttl_cleanup", replace_existing=True,
                              max_instances=1, coalesce=True)
            scheduler.start()
            start_cleanup_scheduler._scheduler = scheduler
    except Exception:
        # Expiry is still enforced on every read and app rerun.
        pass
