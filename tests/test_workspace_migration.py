"""Tests for workspace layout migration (flat → structured).

Covers:
- Fresh workspace with new layout (no migration needed)
- Full legacy workspace (all files migrate)
- Partial migration (only remaining files migrate)
- Idempotent re-runs (second call is a no-op)
- SQLite WAL/SHM companion files
- Empty .openpaw/ cleanup after migration
- File conflict handling (both old and new exist → skip)
- Directory migrations (tools/, crons/, uploads/, etc.)
- memory/sessions → memory/logs rename
- Already-migrated workspace (all files at new locations → no-op)
"""

from pathlib import Path

from openpaw.workspace.migration import (
    _cleanup_empty_dir,
    _migrate_dir,
    _migrate_file,
    migrate_workspace,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(path: Path, content: str = "data") -> None:
    """Create parent dirs and write content to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_legacy_workspace(root: Path) -> None:
    """Populate a workspace with the old flat layout."""
    # Identity files at workspace root
    _write(root / "AGENT.md", "# Agent")
    _write(root / "USER.md", "# User")
    _write(root / "SOUL.md", "# Soul")
    _write(root / "HEARTBEAT.md", "# Heartbeat")

    # Config at root
    _write(root / "agent.yaml", "name: test")
    _write(root / ".env", "KEY=value")

    # State at root
    _write(root / "TASKS.yaml", "tasks: []")
    _write(root / "dynamic_crons.json", "[]")
    _write(root / "heartbeat_log.jsonl", '{"event":"start"}')

    # .openpaw/ directory contents
    _write(root / ".openpaw" / "conversations.db", "sqlite")
    _write(root / ".openpaw" / "sessions.json", "{}")
    _write(root / ".openpaw" / "subagents.yaml", "subagents: []")
    _write(root / ".openpaw" / "token_usage.jsonl", '{"tokens":0}')
    _write(root / ".openpaw" / "vectors.db", "vectors")
    _write(root / ".openpaw" / "browser_cookies.json", "{}")

    # Directories at root
    _write(root / "tools" / "my_tool.py", "# tool")
    _write(root / "skills" / "skill_a" / "SKILL.md", "# Skill")
    _write(root / "crons" / "daily.yaml", "schedule: 0 9 * * *")
    _write(root / "uploads" / "2026-01-01" / "photo.jpg", "imgdata")
    _write(root / "downloads" / "report.pdf", "pdf")
    _write(root / "screenshots" / "page.png", "png")

    # memory/sessions
    _write(root / "memory" / "sessions" / "heartbeat" / "run.jsonl", '{"ok":true}')
    _write(root / "memory" / "conversations" / "conv_1.md", "# Conv")


def _make_new_workspace(root: Path) -> None:
    """Populate a workspace that already uses the new structured layout."""
    _write(root / "agent" / "AGENT.md", "# Agent")
    _write(root / "agent" / "USER.md", "# User")
    _write(root / "agent" / "SOUL.md", "# Soul")
    _write(root / "agent" / "HEARTBEAT.md", "# Heartbeat")

    _write(root / "config" / "agent.yaml", "name: test")
    _write(root / "config" / ".env", "KEY=value")
    _write(root / "config" / "crons" / "daily.yaml", "schedule: 0 9 * * *")

    _write(root / "data" / "conversations.db", "sqlite")
    _write(root / "data" / "sessions.json", "{}")
    _write(root / "data" / "TASKS.yaml", "tasks: []")
    _write(root / "data" / "uploads" / "2026-01-01" / "photo.jpg", "imgdata")

    _write(root / "memory" / "conversations" / "conv_1.md", "# Conv")
    _write(root / "memory" / "logs" / "heartbeat" / "run.jsonl", '{"ok":true}')

    _write(root / "workspace" / "downloads" / "report.pdf", "pdf")
    _write(root / "workspace" / "screenshots" / "page.png", "png")


# ---------------------------------------------------------------------------
# 1. Fresh workspace — new layout, nothing to migrate
# ---------------------------------------------------------------------------


class TestFreshNewLayoutWorkspace:
    """A workspace already using the new structure has no migration actions."""

    def test_returns_empty_action_list(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        actions = migrate_workspace(tmp_path)
        # Only directory-creation entries are allowed (target dirs that may not
        # have existed yet).  No "Moved" entries should appear.
        moved = [a for a in actions if a.startswith("Moved")]
        assert moved == []

    def test_existing_files_are_untouched(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        migrate_workspace(tmp_path)
        assert (tmp_path / "agent" / "AGENT.md").read_text() == "# Agent"
        assert (tmp_path / "data" / "sessions.json").read_text() == "{}"

    def test_idempotent_on_new_layout(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        first = migrate_workspace(tmp_path)
        second = migrate_workspace(tmp_path)
        moved_first = [a for a in first if a.startswith("Moved")]
        moved_second = [a for a in second if a.startswith("Moved")]
        assert moved_first == []
        assert moved_second == []


# ---------------------------------------------------------------------------
# 2. Full legacy workspace — everything migrates
# ---------------------------------------------------------------------------


class TestFullLegacyMigration:
    """All files in old locations should be moved to new locations."""

    def test_identity_files_move_to_agent_dir(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        for fname in ("AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"):
            assert (tmp_path / "agent" / fname).exists(), f"Missing agent/{fname}"
            assert not (tmp_path / fname).exists(), f"Old {fname} still present"

    def test_config_files_move_to_config_dir(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "config" / "agent.yaml").exists()
        assert not (tmp_path / "agent.yaml").exists()

        assert (tmp_path / "config" / ".env").exists()
        assert not (tmp_path / ".env").exists()

    def test_state_files_move_to_data_dir(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        for fname in ("TASKS.yaml", "dynamic_crons.json", "heartbeat_log.jsonl"):
            assert (tmp_path / "data" / fname).exists(), f"Missing data/{fname}"
            assert not (tmp_path / fname).exists(), f"Old {fname} still present"

    def test_openpaw_contents_move_to_data_dir(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        for fname in (
            "conversations.db",
            "sessions.json",
            "subagents.yaml",
            "token_usage.jsonl",
            "vectors.db",
            "browser_cookies.json",
        ):
            assert (tmp_path / "data" / fname).exists(), f"Missing data/{fname}"
            assert not (tmp_path / ".openpaw" / fname).exists(), (
                f".openpaw/{fname} still present"
            )

    def test_tool_and_skills_dirs_move_to_agent(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "agent" / "tools" / "my_tool.py").exists()
        assert not (tmp_path / "tools").exists()

        assert (tmp_path / "agent" / "skills" / "skill_a" / "SKILL.md").exists()
        assert not (tmp_path / "skills").exists()

    def test_crons_dir_moves_to_config(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "config" / "crons" / "daily.yaml").exists()
        assert not (tmp_path / "crons").exists()

    def test_uploads_dir_moves_to_data(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "data" / "uploads" / "2026-01-01" / "photo.jpg").exists()
        assert not (tmp_path / "uploads").exists()

    def test_downloads_and_screenshots_move_to_workspace(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "workspace" / "downloads" / "report.pdf").exists()
        assert not (tmp_path / "downloads").exists()

        assert (tmp_path / "workspace" / "screenshots" / "page.png").exists()
        assert not (tmp_path / "screenshots").exists()

    def test_memory_sessions_renamed_to_memory_logs(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "memory" / "logs" / "heartbeat" / "run.jsonl").exists()
        assert not (tmp_path / "memory" / "sessions").exists()

    def test_memory_conversations_dir_is_unchanged(self, tmp_path: Path) -> None:
        """memory/conversations/ path does not change."""
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "memory" / "conversations" / "conv_1.md").exists()

    def test_file_content_preserved_after_move(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "agent" / "AGENT.md").read_text() == "# Agent"
        assert (tmp_path / "data" / "sessions.json").read_text() == "{}"
        assert (tmp_path / "config" / "agent.yaml").read_text() == "name: test"

    def test_actions_list_is_non_empty(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        actions = migrate_workspace(tmp_path)
        moved = [a for a in actions if a.startswith("Moved")]
        assert len(moved) > 0

    def test_actions_contain_moved_entries(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        actions = migrate_workspace(tmp_path)
        # Check a representative sample
        assert any("AGENT.md" in a for a in actions)
        assert any("sessions.json" in a for a in actions)
        assert any("tools/" in a for a in actions)


# ---------------------------------------------------------------------------
# 3. Partial migration — some files already moved
# ---------------------------------------------------------------------------


class TestPartialMigration:
    """If only some files have been moved, remaining files still migrate."""

    def test_only_unmoved_files_are_migrated(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        # Pre-move a subset of files manually
        (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
        (tmp_path / "AGENT.md").rename(tmp_path / "agent" / "AGENT.md")

        actions = migrate_workspace(tmp_path)
        moved = [a for a in actions if a.startswith("Moved")]

        # AGENT.md was already moved — it should not appear again
        agent_md_moves = [a for a in moved if "AGENT.md" in a]
        assert agent_md_moves == []

        # The other identity files should still be migrated
        assert any("USER.md" in a for a in moved)
        assert any("SOUL.md" in a for a in moved)
        assert any("HEARTBEAT.md" in a for a in moved)

    def test_partial_migration_leaves_all_files_intact(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        # Pre-move config only
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        (tmp_path / "agent.yaml").rename(tmp_path / "config" / "agent.yaml")

        migrate_workspace(tmp_path)

        # Config files
        assert (tmp_path / "config" / "agent.yaml").exists()
        assert (tmp_path / "config" / ".env").exists()
        # Identity files should still have been migrated
        assert (tmp_path / "agent" / "AGENT.md").exists()


# ---------------------------------------------------------------------------
# 4. Idempotent re-runs
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running migrate_workspace twice is safe and produces no new moves."""

    def test_second_run_returns_no_moved_actions(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)
        second_actions = migrate_workspace(tmp_path)

        moved_second = [a for a in second_actions if a.startswith("Moved")]
        assert moved_second == []

    def test_second_run_does_not_alter_files(self, tmp_path: Path) -> None:
        _make_legacy_workspace(tmp_path)
        migrate_workspace(tmp_path)

        content_after_first = (tmp_path / "agent" / "AGENT.md").read_text()
        migrate_workspace(tmp_path)
        content_after_second = (tmp_path / "agent" / "AGENT.md").read_text()

        assert content_after_first == content_after_second


# ---------------------------------------------------------------------------
# 5. SQLite WAL/SHM companion files
# ---------------------------------------------------------------------------


class TestSQLiteCompanionFiles:
    """WAL and SHM files should migrate alongside the main conversations.db."""

    def test_wal_file_migrates_with_db(self, tmp_path: Path) -> None:
        _write(tmp_path / ".openpaw" / "conversations.db", "sqlite")
        _write(tmp_path / ".openpaw" / "conversations.db-wal", "wal")

        migrate_workspace(tmp_path)

        assert (tmp_path / "data" / "conversations.db").exists()
        assert (tmp_path / "data" / "conversations.db-wal").exists()
        assert not (tmp_path / ".openpaw" / "conversations.db-wal").exists()

    def test_shm_file_migrates_with_db(self, tmp_path: Path) -> None:
        _write(tmp_path / ".openpaw" / "conversations.db", "sqlite")
        _write(tmp_path / ".openpaw" / "conversations.db-shm", "shm")

        migrate_workspace(tmp_path)

        assert (tmp_path / "data" / "conversations.db-shm").exists()
        assert not (tmp_path / ".openpaw" / "conversations.db-shm").exists()

    def test_all_three_db_files_migrate_together(self, tmp_path: Path) -> None:
        _write(tmp_path / ".openpaw" / "conversations.db", "sqlite")
        _write(tmp_path / ".openpaw" / "conversations.db-wal", "wal")
        _write(tmp_path / ".openpaw" / "conversations.db-shm", "shm")

        migrate_workspace(tmp_path)

        for fname in ("conversations.db", "conversations.db-wal", "conversations.db-shm"):
            assert (tmp_path / "data" / fname).exists(), f"Missing data/{fname}"
            assert not (tmp_path / ".openpaw" / fname).exists(), (
                f".openpaw/{fname} still present"
            )

    def test_missing_wal_shm_does_not_error(self, tmp_path: Path) -> None:
        """Only the main DB exists — migration should complete without error."""
        _write(tmp_path / ".openpaw" / "conversations.db", "sqlite")

        actions = migrate_workspace(tmp_path)

        assert (tmp_path / "data" / "conversations.db").exists()
        # No WAL/SHM files mentioned in actions (they didn't exist)
        assert not any("wal" in a for a in actions)
        assert not any("shm" in a for a in actions)


# ---------------------------------------------------------------------------
# 6. Empty .openpaw/ cleanup
# ---------------------------------------------------------------------------


class TestOpenpawCleanup:
    """The .openpaw/ directory should be removed after its contents are migrated."""

    def test_empty_openpaw_is_removed(self, tmp_path: Path) -> None:
        _write(tmp_path / ".openpaw" / "sessions.json", "{}")

        migrate_workspace(tmp_path)

        assert not (tmp_path / ".openpaw").exists()

    def test_non_empty_openpaw_is_not_removed(self, tmp_path: Path) -> None:
        """If .openpaw/ still has files after migration, leave it alone."""
        _write(tmp_path / ".openpaw" / "sessions.json", "{}")
        # Add an unrecognised file that won't be migrated
        _write(tmp_path / ".openpaw" / "unknown_file.dat", "mystery")

        migrate_workspace(tmp_path)

        # .openpaw/ should still exist because unknown_file.dat remains
        assert (tmp_path / ".openpaw").exists()
        assert (tmp_path / ".openpaw" / "unknown_file.dat").exists()

    def test_absent_openpaw_does_not_error(self, tmp_path: Path) -> None:
        """No .openpaw/ directory at all — should be a no-op."""
        migrate_workspace(tmp_path)  # Must not raise

    def test_cleanup_appears_in_actions(self, tmp_path: Path) -> None:
        _write(tmp_path / ".openpaw" / "sessions.json", "{}")

        actions = migrate_workspace(tmp_path)
        removed = [a for a in actions if "Removed" in a and ".openpaw" in a]
        assert len(removed) == 1


# ---------------------------------------------------------------------------
# 7. File conflict — both old and new exist
# ---------------------------------------------------------------------------


class TestFileConflict:
    """When both source and destination exist, skip and warn. Never overwrite."""

    def test_existing_destination_is_not_overwritten(self, tmp_path: Path) -> None:
        _write(tmp_path / "AGENT.md", "old content")
        (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
        _write(tmp_path / "agent" / "AGENT.md", "new content")

        migrate_workspace(tmp_path)

        # Destination retains its content
        assert (tmp_path / "agent" / "AGENT.md").read_text() == "new content"

    def test_source_is_left_in_place_on_conflict(self, tmp_path: Path) -> None:
        _write(tmp_path / "USER.md", "original")
        (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
        _write(tmp_path / "agent" / "USER.md", "migrated already")

        migrate_workspace(tmp_path)

        # Source file is NOT deleted when there's a conflict
        assert (tmp_path / "USER.md").exists()
        assert (tmp_path / "USER.md").read_text() == "original"

    def test_conflict_does_not_appear_in_actions(self, tmp_path: Path) -> None:
        _write(tmp_path / "SOUL.md", "old")
        (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
        _write(tmp_path / "agent" / "SOUL.md", "new")

        actions = migrate_workspace(tmp_path)

        soul_moves = [a for a in actions if "SOUL.md" in a and a.startswith("Moved")]
        assert soul_moves == []

    def test_conflict_on_one_file_does_not_block_others(self, tmp_path: Path) -> None:
        """A conflict on AGENT.md should not prevent USER.md from migrating."""
        _write(tmp_path / "AGENT.md", "old agent")
        _write(tmp_path / "USER.md", "user content")
        (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
        _write(tmp_path / "agent" / "AGENT.md", "already there")

        migrate_workspace(tmp_path)

        # USER.md should have migrated despite AGENT.md conflict
        assert (tmp_path / "agent" / "USER.md").exists()
        assert (tmp_path / "agent" / "USER.md").read_text() == "user content"


# ---------------------------------------------------------------------------
# 8. Directory migration
# ---------------------------------------------------------------------------


class TestDirectoryMigration:
    """Directories are moved with their full contents."""

    def test_tools_dir_migrates_with_contents(self, tmp_path: Path) -> None:
        _write(tmp_path / "tools" / "alpha.py", "# alpha")
        _write(tmp_path / "tools" / "beta.py", "# beta")

        migrate_workspace(tmp_path)

        assert (tmp_path / "agent" / "tools" / "alpha.py").exists()
        assert (tmp_path / "agent" / "tools" / "beta.py").exists()
        assert not (tmp_path / "tools").exists()

    def test_crons_dir_migrates_with_contents(self, tmp_path: Path) -> None:
        _write(tmp_path / "crons" / "daily.yaml", "schedule: 0 9 * * *")
        _write(tmp_path / "crons" / "weekly.yml", "schedule: 0 0 * * 0")

        migrate_workspace(tmp_path)

        assert (tmp_path / "config" / "crons" / "daily.yaml").exists()
        assert (tmp_path / "config" / "crons" / "weekly.yml").exists()
        assert not (tmp_path / "crons").exists()

    def test_uploads_dir_migrates_with_date_partitions(self, tmp_path: Path) -> None:
        _write(tmp_path / "uploads" / "2026-01-01" / "img.jpg", "jpeg")
        _write(tmp_path / "uploads" / "2026-01-02" / "doc.pdf", "pdf")

        migrate_workspace(tmp_path)

        assert (tmp_path / "data" / "uploads" / "2026-01-01" / "img.jpg").exists()
        assert (tmp_path / "data" / "uploads" / "2026-01-02" / "doc.pdf").exists()
        assert not (tmp_path / "uploads").exists()

    def test_dir_conflict_leaves_source_in_place(self, tmp_path: Path) -> None:
        """If destination directory exists, skip move and preserve source."""
        _write(tmp_path / "tools" / "old_tool.py", "# old")
        (tmp_path / "agent" / "tools").mkdir(parents=True, exist_ok=True)
        _write(tmp_path / "agent" / "tools" / "new_tool.py", "# new")

        migrate_workspace(tmp_path)

        # Old source dir still exists (not moved because destination exists)
        assert (tmp_path / "tools").exists()
        # New destination is untouched
        assert (tmp_path / "agent" / "tools" / "new_tool.py").exists()
        # Old file is NOT moved into destination
        assert not (tmp_path / "agent" / "tools" / "old_tool.py").exists()

    def test_memory_sessions_renamed_to_logs(self, tmp_path: Path) -> None:
        _write(tmp_path / "memory" / "sessions" / "heartbeat" / "run.jsonl", '{"ok":1}')
        _write(tmp_path / "memory" / "sessions" / "cron" / "job.jsonl", '{"cron":1}')

        migrate_workspace(tmp_path)

        assert (tmp_path / "memory" / "logs" / "heartbeat" / "run.jsonl").exists()
        assert (tmp_path / "memory" / "logs" / "cron" / "job.jsonl").exists()
        assert not (tmp_path / "memory" / "sessions").exists()


# ---------------------------------------------------------------------------
# 9. Target directory creation
# ---------------------------------------------------------------------------


class TestTargetDirectoryCreation:
    """All required target directories should be created by migrate_workspace."""

    def test_all_top_level_dirs_are_created(self, tmp_path: Path) -> None:
        migrate_workspace(tmp_path)

        for d in ("agent", "config", "data", "memory", "workspace"):
            assert (tmp_path / d).is_dir(), f"Missing top-level directory: {d}/"

    def test_memory_subdirs_are_created(self, tmp_path: Path) -> None:
        migrate_workspace(tmp_path)

        assert (tmp_path / "memory" / "conversations").is_dir()
        assert (tmp_path / "memory" / "logs").is_dir()

    def test_creation_actions_in_result(self, tmp_path: Path) -> None:
        actions = migrate_workspace(tmp_path)
        created = [a for a in actions if a.startswith("Created")]
        assert len(created) > 0


# ---------------------------------------------------------------------------
# 10. Already-migrated workspace — complete no-op
# ---------------------------------------------------------------------------


class TestAlreadyMigratedWorkspace:
    """A workspace fully on the new layout produces zero move actions."""

    def test_no_moves_on_new_layout(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        actions = migrate_workspace(tmp_path)
        moved = [a for a in actions if a.startswith("Moved")]
        assert moved == []

    def test_no_removed_entries_on_new_layout(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        actions = migrate_workspace(tmp_path)
        removed = [a for a in actions if a.startswith("Removed")]
        assert removed == []

    def test_files_remain_at_new_locations(self, tmp_path: Path) -> None:
        _make_new_workspace(tmp_path)
        migrate_workspace(tmp_path)

        assert (tmp_path / "agent" / "AGENT.md").read_text() == "# Agent"
        assert (tmp_path / "config" / "agent.yaml").read_text() == "name: test"
        assert (tmp_path / "data" / "sessions.json").read_text() == "{}"


# ---------------------------------------------------------------------------
# 11. Unit tests for private helpers
# ---------------------------------------------------------------------------


class TestMigrateFileHelper:
    """Unit tests for the _migrate_file internal helper."""

    def test_moves_file_when_source_exists(self, tmp_path: Path) -> None:
        _write(tmp_path / "old.txt", "content")
        actions: list[str] = []
        _migrate_file(tmp_path, "old.txt", "subdir/new.txt", actions)

        assert (tmp_path / "subdir" / "new.txt").read_text() == "content"
        assert not (tmp_path / "old.txt").exists()
        assert any("old.txt" in a for a in actions)

    def test_no_op_when_source_missing(self, tmp_path: Path) -> None:
        actions: list[str] = []
        _migrate_file(tmp_path, "nonexistent.txt", "target.txt", actions)
        assert actions == []

    def test_skips_when_destination_exists(self, tmp_path: Path) -> None:
        _write(tmp_path / "old.txt", "source")
        _write(tmp_path / "new.txt", "destination")
        actions: list[str] = []
        _migrate_file(tmp_path, "old.txt", "new.txt", actions)

        assert (tmp_path / "new.txt").read_text() == "destination"
        assert (tmp_path / "old.txt").exists()
        assert actions == []

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        _write(tmp_path / "file.txt", "hello")
        actions: list[str] = []
        _migrate_file(tmp_path, "file.txt", "a/b/c/file.txt", actions)

        assert (tmp_path / "a" / "b" / "c" / "file.txt").exists()


class TestMigrateDirHelper:
    """Unit tests for the _migrate_dir internal helper."""

    def test_moves_directory_when_source_exists(self, tmp_path: Path) -> None:
        _write(tmp_path / "old_dir" / "file.txt", "content")
        actions: list[str] = []
        _migrate_dir(tmp_path, "old_dir", "new_dir", actions)

        assert (tmp_path / "new_dir" / "file.txt").read_text() == "content"
        assert not (tmp_path / "old_dir").exists()
        assert any("old_dir" in a for a in actions)

    def test_no_op_when_source_missing(self, tmp_path: Path) -> None:
        actions: list[str] = []
        _migrate_dir(tmp_path, "missing_dir", "target_dir", actions)
        assert actions == []

    def test_skips_when_destination_exists(self, tmp_path: Path) -> None:
        _write(tmp_path / "old_dir" / "old.txt", "old")
        (tmp_path / "new_dir").mkdir()
        _write(tmp_path / "new_dir" / "new.txt", "new")
        actions: list[str] = []
        _migrate_dir(tmp_path, "old_dir", "new_dir", actions)

        assert (tmp_path / "old_dir").exists()
        assert (tmp_path / "new_dir" / "new.txt").read_text() == "new"
        assert actions == []


class TestCleanupEmptyDirHelper:
    """Unit tests for the _cleanup_empty_dir internal helper."""

    def test_removes_empty_directory(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        actions: list[str] = []
        _cleanup_empty_dir(empty_dir, actions)

        assert not empty_dir.exists()
        assert any("Removed" in a for a in actions)

    def test_does_not_remove_non_empty_directory(self, tmp_path: Path) -> None:
        non_empty = tmp_path / "nonempty"
        non_empty.mkdir()
        _write(non_empty / "file.txt", "data")
        actions: list[str] = []
        _cleanup_empty_dir(non_empty, actions)

        assert non_empty.exists()
        assert actions == []

    def test_no_op_when_directory_absent(self, tmp_path: Path) -> None:
        actions: list[str] = []
        _cleanup_empty_dir(tmp_path / "does_not_exist", actions)
        assert actions == []
