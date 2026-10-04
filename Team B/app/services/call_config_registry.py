"""
Call Configuration Registry & Prompt Contract
=============================================
Thread-safe, TTL-based registry for ephemeral outbound call scripts and custom prompts.
Enforces Level 3 prompt contract, correlation isolation, and lifecycle cleanup.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from loguru import logger


def compute_prompt_hash(prompt_text: str) -> str:
    """Computes a truncated SHA-256 hash for secure observability without exposing content."""
    if not prompt_text:
        return "empty"
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]


def normalize_prompt_text(raw_text: str) -> str:
    """
    Normalizes harmless control characters and line endings without altering
    the semantic meaning or natural language content.
    """
    if not raw_text:
        return ""
    # Strip null bytes and non-printable control characters (except newline, tab)
    cleaned = raw_text.replace("\0", "")
    # Normalize Windows CRLF to standard LF
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


class CallPromptConfig(BaseModel):
    """
    Strongly-validated contract for call-specific AI agent prompts and scripts.
    Preserves backward compatibility: missing or empty prompts degrade to default behavior.
    """
    model_config = ConfigDict(extra="ignore")

    call_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2500,
        description="Operator-provided call script or directive (max 2500 characters)."
    )
    objective: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Optional high-level call objective summary."
    )
    custom_qualification_criteria: List[str] = Field(
        default_factory=list,
        description="Optional list of specific qualification criteria for this call."
    )

    @field_validator("call_prompt", mode="before")
    @classmethod
    def validate_and_normalize_prompt(cls, v: Any) -> str:
        if v is None:
            raise ValueError("call_prompt cannot be None")
        normalized = normalize_prompt_text(str(v))
        if not normalized:
            raise ValueError("call_prompt cannot be empty or whitespace-only")
        if len(normalized) > 2500:
            raise ValueError(f"call_prompt exceeds maximum length of 2500 characters (got {len(normalized)})")
        return normalized

    @field_validator("objective", mode="before")
    @classmethod
    def validate_objective(cls, v: Any) -> Optional[str]:
        if not v:
            return None
        cleaned = normalize_prompt_text(str(v))
        if len(cleaned) > 300:
            raise ValueError(f"objective exceeds maximum length of 300 characters (got {len(cleaned)})")
        return cleaned or None

    @field_validator("custom_qualification_criteria", mode="before")
    @classmethod
    def validate_criteria(cls, v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, str):
            items = [normalize_prompt_text(i) for i in v.split(",") if normalize_prompt_text(i)]
            return items
        if isinstance(v, (list, tuple)):
            cleaned = []
            for item in v:
                if item:
                    c = normalize_prompt_text(str(item))
                    if c:
                        cleaned.append(c)
            return cleaned
        return []

    def get_audit_meta(self) -> Dict[str, Any]:
        """Returns safe audit metadata without logging sensitive prompt content."""
        return {
            "length": len(self.call_prompt),
            "sha256": compute_prompt_hash(self.call_prompt),
            "has_objective": bool(self.objective),
            "criteria_count": len(self.custom_qualification_criteria),
        }


class _RegistryEntry:
    __slots__ = ("config", "expires_at", "session_id", "dispatch_id", "created_at")

    def __init__(
        self,
        config: CallPromptConfig,
        ttl_seconds: float,
        session_id: Optional[str] = None,
        dispatch_id: Optional[str] = None,
    ):
        self.config = config
        self.created_at = time.time()
        self.expires_at = self.created_at + max(0.01, float(ttl_seconds))
        self.session_id = session_id
        self.dispatch_id = dispatch_id

    def is_expired(self, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        return t >= self.expires_at


class CallConfigRegistry:
    """
    Thread-safe, TTL-based in-memory registry for ephemeral outbound call configurations.
    Ensures that Call A's prompt never leaks to Call B and is cleaned upon session end.
    """

    DEFAULT_TTL_SECONDS: float = 900.0  # 15 minutes: covers queueing, dialing, ringing, session duration

    def __init__(self, default_ttl: float = DEFAULT_TTL_SECONDS):
        self._lock = threading.RLock()
        self._by_session: Dict[str, _RegistryEntry] = {}
        self._by_dispatch: Dict[str, _RegistryEntry] = {}
        self._default_ttl = default_ttl

    def set(
        self,
        session_id: str,
        config: CallPromptConfig,
        dispatch_id: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """
        Registers a call prompt configuration bound to session_id and optionally dispatch_id.
        """
        if not session_id or not isinstance(config, CallPromptConfig):
            logger.warning("[CALL_PROMPT_REJECTED] Invalid arguments to CallConfigRegistry.set")
            return

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        entry = _RegistryEntry(
            config=config,
            ttl_seconds=ttl,
            session_id=session_id,
            dispatch_id=dispatch_id,
        )

        with self._lock:
            self._purge_expired_locked()
            self._by_session[session_id] = entry
            if dispatch_id:
                self._by_dispatch[dispatch_id] = entry

        meta = config.get_audit_meta()
        logger.info(
            f"[CALL_PROMPT_ATTACHED] Registered call configuration | "
            f"session_id={session_id} | dispatch_id={dispatch_id or 'none'} | "
            f"length={meta['length']} | sha256={meta['sha256']} | ttl={ttl}s"
        )

    def get(self, session_id: str) -> Optional[CallPromptConfig]:
        """
        Retrieves the CallPromptConfig for a session_id.
        Returns None if not found or expired. Never raises.
        """
        if not session_id:
            return None

        with self._lock:
            entry = self._by_session.get(session_id)
            if not entry:
                return None
            if entry.is_expired():
                self._delete_entry_locked(entry, reason="ttl_expired")
                return None
            return entry.config

    def get_by_dispatch(self, dispatch_id: str) -> Optional[CallPromptConfig]:
        """
        Retrieves the CallPromptConfig for a dispatch_id.
        Returns None if not found or expired. Never raises.
        """
        if not dispatch_id:
            return None

        with self._lock:
            entry = self._by_dispatch.get(dispatch_id)
            if not entry:
                return None
            if entry.is_expired():
                self._delete_entry_locked(entry, reason="ttl_expired")
                return None
            return entry.config

    def delete(
        self,
        session_id: Optional[str] = None,
        dispatch_id: Optional[str] = None,
        reason: str = "session_closed",
    ) -> bool:
        """
        Evicts a configuration entry by session_id or dispatch_id.
        """
        with self._lock:
            entry = None
            if session_id and session_id in self._by_session:
                entry = self._by_session[session_id]
            elif dispatch_id and dispatch_id in self._by_dispatch:
                entry = self._by_dispatch[dispatch_id]

            if entry:
                self._delete_entry_locked(entry, reason=reason)
                return True
            return False

    def _delete_entry_locked(self, entry: _RegistryEntry, reason: str = "cleaned") -> None:
        """Helper to remove entry from all internal lookups under lock."""
        sid = entry.session_id
        did = entry.dispatch_id
        if sid and sid in self._by_session:
            del self._by_session[sid]
        if did and did in self._by_dispatch:
            del self._by_dispatch[did]

        meta = entry.config.get_audit_meta()
        logger.info(
            f"[CALL_PROMPT_EVICTED] Purged call configuration | reason={reason} | "
            f"session_id={sid or 'none'} | dispatch_id={did or 'none'} | "
            f"sha256={meta['sha256']}"
        )

    def _purge_expired_locked(self) -> int:
        now = time.time()
        expired_sessions = [
            sid for sid, entry in self._by_session.items() if entry.is_expired(now)
        ]
        for sid in expired_sessions:
            entry = self._by_session.get(sid)
            if entry:
                self._delete_entry_locked(entry, reason="ttl_expired")
        return len(expired_sessions)

    def cleanup_expired(self) -> int:
        """Public sweep for periodic background cleanup."""
        with self._lock:
            return self._purge_expired_locked()

    def clear(self) -> None:
        """Clears all entries (useful in testing)."""
        with self._lock:
            self._by_session.clear()
            self._by_dispatch.clear()

    def count(self) -> int:
        """Returns total active entries."""
        with self._lock:
            self._purge_expired_locked()
            return len(self._by_session)


# Global singleton registry instance
call_config_registry = CallConfigRegistry()
