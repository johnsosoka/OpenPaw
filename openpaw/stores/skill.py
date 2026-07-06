"""Single write path for agent skills (ADR-105).

Every programmatic writer — the ``manage_skill`` tool, the skill-builder
subprocess, the dream sequence — goes through ``SkillStore``. The store owns
the validation gates, frontmatter stamping, atomic writes, lifecycle event
emission (ADR-106), and the hot-reload trigger. Direct ``write_file`` into
``agent/skills/`` remains physically possible; unmanaged files simply get
default provenance on next load — the paved path is strictly better.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import yaml
from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from openpaw.core.paths import SKILLS_DIR
from openpaw.core.skill_file import (
    MAX_DESCRIPTION_LENGTH as _MAX_DESCRIPTION_LENGTH,
)
from openpaw.core.skill_file import SKILL_FILENAME, load_skill_file
from openpaw.model.skill import SkillCreatedBy, SkillInfo, SkillStatus
from openpaw.model.status_event import StatusEmitter, StatusEvent, StatusEventKind
from openpaw.stores.skill_lint import lint_skill_content

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_RESERVED_PREFIX = "_framework"

# Approval policy modes (gate 4). "immediate" -> active + hot-reload;
# "staged" -> staged + awaits /skills approve.
APPROVAL_IMMEDIATE = "immediate"
APPROVAL_STAGED = "staged"


@dataclass(frozen=True)
class SkillLimits:
    """Budget knobs for skill writes (learning.limits config, ADR-105 gate 2)."""

    max_skill_tokens: int = 1_200
    max_skills: int = 30


@dataclass(frozen=True)
class SkillValidationError:
    """Structured gate failure — agent-visible via the manage_skill tool,
    logged for background paths. No partial writes ever occur.

    Attributes:
        gate: Which gate failed ("schema" | "budget" | "content" | "policy").
        reason: Human-readable failure description.
    """

    gate: str
    reason: str


class SkillRejectedError(Exception):
    """Raised when a skill write fails one or more validation gates."""

    def __init__(self, errors: list[SkillValidationError]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"[{e.gate}] {e.reason}" for e in errors))


class SkillStore:
    """Manages validated, atomic writes of workspace skills.

    Follows the established store pattern (threading.Lock + atomic tmp-rename
    writes, workspace-local; cf. openpaw/stores/subagent.py). Blocking file
    I/O runs in a thread pool via asyncio.to_thread().

    Validation gates, applied in order before any write:
        1. schema  — name slug-valid; not shadowing the reserved
                     _framework/* namespace; no collision on create.
        2. budget  — content within max_skill_tokens; workspace under
                     max_skills active skills (on create).
        3. content — deny-pattern lint (credentials, gate-bypass text).
        4. policy  — approval mode decides the written status:
                     immediate -> active + hot-reload; staged -> staged.

    Lifecycle events (skill.created/updated/staged/approved/equipped/
    deprecated/rejected) are emitted through the injected StatusEmitter with
    {name, version, created_by, workspace} payloads. All events of one
    operation share a run_id.

    Example:
        >>> store = SkillStore(
        ...     workspace_path=Path("agent_workspaces/devin"),
        ...     workspace="devin",
        ...     limits=SkillLimits(),
        ...     emitter=status_bus,
        ...     reload_trigger=reload_skills_async,
        ... )
        >>> await store.create(
        ...     name="telegram-digest-format",
        ...     description="How John likes his morning digests formatted",
        ...     content="...",
        ...     created_by=SkillCreatedBy.AGENT,
        ...     source="telegram:123456:conv_2026-07-02",
        ...     approval="immediate",
        ... )
    """

    def __init__(
        self,
        workspace_path: Path,
        workspace: str,
        limits: SkillLimits,
        emitter: StatusEmitter,
        reload_trigger: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the store.

        Args:
            workspace_path: Workspace root; skills live under agent/skills/.
            workspace: Workspace name for event payloads.
            limits: Token/count budgets from learning.limits config.
            emitter: ADR-106 status emitter for lifecycle events.
            reload_trigger: Async callback invoking the workspace's
                reload_skills path (rescan, merge, materialize, swap
                workspace.skills, rebuild agent). Called best-effort after
                every write that changes the active skill set.
        """
        self._skills_dir = Path(workspace_path) / str(SKILLS_DIR)
        self._workspace = workspace
        self._limits = limits
        self._emitter = emitter
        self._reload_trigger = reload_trigger
        self._lock = Lock()

    # -- Public API -----------------------------------------------------------

    async def create(
        self,
        name: str,
        description: str,
        content: str,
        created_by: SkillCreatedBy,
        source: str,
        approval: str,
    ) -> SkillInfo:
        """Validate and write a new skill; emit events; maybe hot-reload.

        Args:
            name: Slug-valid skill name (also the directory name).
            description: Short description for prompt injection.
            content: Skill body markdown (frontmatter is stamped by the store).
            created_by: Provenance of this write.
            source: Provenance reference (e.g. a session key).
            approval: "immediate" (write active + reload) or "staged".

        Returns:
            The written SkillInfo.

        Raises:
            SkillRejectedError: One or more gates failed; nothing written.
        """
        status = self._status_for(approval)
        skill = SkillInfo(
            name=name,
            description=description,
            content=content,
            path=self._skills_dir / name,
            read_path=f"agent/skills/{name}/SKILL.md",
            created_by=created_by,
            source_ref=source,
            updated_at=datetime.now(UTC),
            status=status,
        )
        await asyncio.to_thread(self._validate_and_write_sync, skill, True)

        run_id = uuid.uuid4().hex
        if status is SkillStatus.ACTIVE:
            await self._emit(StatusEventKind.SKILL_CREATED, skill, run_id)
            await self._trigger_reload(skill, run_id)
        else:
            await self._emit(StatusEventKind.SKILL_STAGED, skill, run_id)
        return skill

    async def update(
        self,
        name: str,
        content: str,
        created_by: SkillCreatedBy,
        source: str,
        approval: str,
        description: str | None = None,
    ) -> SkillInfo:
        """Validate and rewrite an existing skill, bumping its version.

        Args:
            name: Name of the existing skill to update.
            content: New skill body markdown.
            created_by: Provenance of this write.
            source: Provenance reference.
            approval: "immediate" or "staged".
            description: New description, or None to keep the existing one.

        Returns:
            The written SkillInfo with an incremented version.

        Raises:
            SkillRejectedError: Skill missing or gates failed; nothing written.
        """
        existing = await asyncio.to_thread(self._read_skill_sync, name)
        status = self._status_for(approval)
        skill = replace(
            existing,
            description=description if description is not None else existing.description,
            content=content,
            version=existing.version + 1,
            created_by=created_by,
            source_ref=source,
            updated_at=datetime.now(UTC),
            status=status,
        )
        await asyncio.to_thread(self._validate_and_write_sync, skill, False)

        run_id = uuid.uuid4().hex
        if status is SkillStatus.ACTIVE:
            await self._emit(StatusEventKind.SKILL_UPDATED, skill, run_id)
            await self._trigger_reload(skill, run_id)
        else:
            await self._emit(StatusEventKind.SKILL_STAGED, skill, run_id)
        return skill

    async def approve(self, name: str) -> SkillInfo:
        """Promote a staged skill to active (/skills approve <name>).

        Raises:
            SkillRejectedError: Skill missing or not staged.
        """
        skill = await asyncio.to_thread(
            self._set_status_sync, name, SkillStatus.ACTIVE, require=SkillStatus.STAGED
        )
        run_id = uuid.uuid4().hex
        await self._emit(StatusEventKind.SKILL_APPROVED, skill, run_id)
        await self._trigger_reload(skill, run_id)
        return skill

    async def reject(self, name: str) -> SkillInfo:
        """Reject a staged skill (/skills reject <name>).

        Design choice: rejection marks the skill ``status: deprecated`` rather
        than deleting it — the file stays on disk (audit trail, recoverable by
        a human) and the loader already skips deprecated skills. No reload is
        needed because a staged skill was never in the prompt.

        Raises:
            SkillRejectedError: Skill missing or not staged.
        """
        skill = await asyncio.to_thread(
            self._set_status_sync,
            name,
            SkillStatus.DEPRECATED,
            require=SkillStatus.STAGED,
        )
        await self._emit(StatusEventKind.SKILL_REJECTED, skill, uuid.uuid4().hex)
        return skill

    async def deprecate(self, name: str) -> SkillInfo:
        """Mark a skill deprecated — skipped by the loader, kept on disk.

        Raises:
            SkillRejectedError: Skill does not exist.
        """
        skill = await asyncio.to_thread(
            self._set_status_sync, name, SkillStatus.DEPRECATED
        )
        run_id = uuid.uuid4().hex
        await self._emit(StatusEventKind.SKILL_DEPRECATED, skill, run_id)
        # Reload so a previously-active skill is un-injected from the prompt.
        await self._trigger_reload(skill, run_id)
        return skill

    async def list_skills(self) -> list[SkillInfo]:
        """List all store-managed skills, including staged and deprecated.

        Skips ``_``-prefixed directories (private / _framework materializations)
        and unparseable files. Sorted by directory name.

        Returns:
            All workspace skills regardless of lifecycle status.
        """
        return await asyncio.to_thread(self._list_skills_sync)

    # -- Validation gates (ADR-105 §3) -----------------------------------------

    def _validate_and_write_sync(self, skill: SkillInfo, is_new: bool) -> None:
        """Run all gates, then write — one thread hop for the blocking work.

        Gates and write happen under one lock so the invariants the gates
        enforce (name collision, max_skills budget) hold atomically against
        concurrent writers (manage_skill tool vs background learning loop).

        Raises:
            SkillRejectedError: One or more gates failed; nothing written.
        """
        with self._lock:
            self._run_gates(skill, is_new)
            self._write_skill_locked(skill)

    def _run_gates(self, skill: SkillInfo, is_new: bool) -> None:
        """Apply the gates in order; collect all failures; reject atomically."""
        errors: list[SkillValidationError] = []

        # Gate 1 — schema
        if not _SLUG_RE.match(skill.name):
            errors.append(
                SkillValidationError(
                    "schema",
                    f"name not slug-valid: {skill.name!r} "
                    "(lowercase letters, digits, hyphens; 2-63 chars)",
                )
            )
        if skill.name.startswith(_RESERVED_PREFIX):
            errors.append(
                SkillValidationError(
                    "schema", "workspace skills may not shadow _framework/*"
                )
            )
        if is_new and (self._skills_dir / skill.name / SKILL_FILENAME).exists():
            errors.append(
                SkillValidationError("schema", f"skill already exists: {skill.name}")
            )

        # Gate 2 — budget
        tokens = count_tokens_approximately([HumanMessage(skill.content)])
        if tokens > self._limits.max_skill_tokens:
            errors.append(
                SkillValidationError(
                    "budget",
                    f"~{tokens} tokens exceeds "
                    f"max_skill_tokens={self._limits.max_skill_tokens}",
                )
            )
        if is_new and self._count_active_sync() >= self._limits.max_skills:
            errors.append(
                SkillValidationError(
                    "budget",
                    f"workspace at max_skills={self._limits.max_skills} active skills",
                )
            )

        # Gate 1b — description cap (mirrors the loader's read-time cap; the
        # description is prompt-injected for SUMMARY skills, so it is bounded
        # and linted like content).
        if len(skill.description) > _MAX_DESCRIPTION_LENGTH:
            errors.append(
                SkillValidationError(
                    "schema",
                    f"description exceeds {_MAX_DESCRIPTION_LENGTH} characters",
                )
            )

        # Gate 3 — content lint. The description is linted too: for SUMMARY
        # skills (the default inject mode) the description is the ONLY text
        # that reaches the system prompt, so it is exactly as
        # injection-sensitive as the body.
        errors.extend(
            SkillValidationError("content", reason)
            for reason in lint_skill_content(f"{skill.description}\n{skill.content}")
        )

        # Gate 4 — policy is not a rejection gate: the approval mode already
        # decided the status stamped on the skill (immediate -> active,
        # staged -> staged). It lives conceptually here so the policy decision
        # and the gates share one audit point.

        if errors:
            raise SkillRejectedError(errors)

    @staticmethod
    def _status_for(approval: str) -> SkillStatus:
        """Map an approval mode to the status a write is stamped with."""
        return SkillStatus.ACTIVE if approval == APPROVAL_IMMEDIATE else SkillStatus.STAGED

    # -- Persistence internals --------------------------------------------------

    def _write_skill_sync(self, skill: SkillInfo) -> None:
        """Atomic write: render SKILL.md, tmp + rename under the lock."""
        with self._lock:
            self._write_skill_locked(skill)

    def _write_skill_locked(self, skill: SkillInfo) -> None:
        """Write body — caller holds self._lock."""
        skill_dir = self._skills_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / SKILL_FILENAME
        tmp = target.with_suffix(".tmp")
        tmp.write_text(self._render(skill), encoding="utf-8")
        tmp.replace(target)  # POSIX-atomic rename
        logger.info(
            f"Skill written: {skill.name} v{skill.version} ({skill.status.value})"
        )

    @staticmethod
    def _render(skill: SkillInfo) -> str:
        """Render frontmatter + body. yaml.safe_dump handles value escaping."""
        frontmatter = {
            "name": skill.name,
            "description": skill.description,
            "inject": skill.inject.value,
            "version": skill.version,
            "created_by": skill.created_by.value,
            "source": skill.source_ref,
            "updated_at": (
                skill.updated_at.isoformat() if skill.updated_at is not None else None
            ),
            "status": skill.status.value,
        }
        dumped = yaml.safe_dump(
            frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        return f"---\n{dumped}---\n\n{skill.content.strip()}\n"

    def _read_skill_sync(self, name: str) -> SkillInfo:
        """Parse an existing skill or raise a schema-gate rejection."""
        skill_dir = self._skills_dir / name
        skill_file = skill_dir / SKILL_FILENAME
        if not skill_file.exists():
            raise SkillRejectedError(
                [SkillValidationError("schema", f"skill does not exist: {name}")]
            )
        return load_skill_file(skill_dir, skill_file)

    def _set_status_sync(
        self,
        name: str,
        status: SkillStatus,
        require: SkillStatus | None = None,
    ) -> SkillInfo:
        """Rewrite an existing skill with a new status and updated_at.

        Args:
            name: Skill directory name.
            status: New lifecycle status.
            require: If set, the skill's current status must match.

        Raises:
            SkillRejectedError: Skill missing or current status mismatch.
        """
        existing = self._read_skill_sync(name)
        if require is not None and existing.status is not require:
            raise SkillRejectedError(
                [
                    SkillValidationError(
                        "policy",
                        f"skill '{name}' is {existing.status.value}, "
                        f"expected {require.value}",
                    )
                ]
            )
        skill = replace(existing, status=status, updated_at=datetime.now(UTC))
        self._write_skill_sync(skill)
        return skill

    def _count_active_sync(self) -> int:
        """Count active workspace skills (skips _ dirs, staged, deprecated)."""
        return sum(
            1 for s in self._list_skills_sync() if s.status is SkillStatus.ACTIVE
        )

    def _list_skills_sync(self) -> list[SkillInfo]:
        """Scan the skills directory, tolerating unparseable entries."""
        if not self._skills_dir.exists():
            return []
        skills: list[SkillInfo] = []
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue
            skill_file = skill_dir / SKILL_FILENAME
            if not skill_file.exists():
                continue
            try:
                skills.append(load_skill_file(skill_dir, skill_file))
            except Exception as e:
                logger.error(f"Failed to parse skill '{skill_dir.name}': {e}")
        return skills

    # -- Events + reload ---------------------------------------------------------

    async def _emit(self, kind: StatusEventKind, skill: SkillInfo, run_id: str) -> None:
        """Emit a lifecycle event ({name, version, created_by, workspace})."""
        await self._emitter.emit(
            StatusEvent(
                kind=kind,
                workspace=self._workspace,
                session_key=None,
                run_id=run_id,
                node="skill_store",
                payload={
                    "name": skill.name,
                    "version": skill.version,
                    "created_by": skill.created_by.value,
                    "workspace": self._workspace,
                },
            )
        )

    async def _trigger_reload(self, skill: SkillInfo, run_id: str) -> None:
        """Fire the hot-reload callback; emit skill.equipped on success.

        Reload is best-effort from the store's perspective — a reload failure
        leaves the file written, is surfaced via logs, and suppresses the
        equipped event. It is never a partial write.
        """
        try:
            await self._reload_trigger()
        except Exception:
            logger.error(
                f"Skill reload failed after writing {skill.name}", exc_info=True
            )
            return
        await self._emit(StatusEventKind.SKILL_EQUIPPED, skill, run_id)
