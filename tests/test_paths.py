"""Tests for openpaw/core/paths.py — workspace path constants."""

from pathlib import PurePosixPath

import openpaw.core.paths as paths
from openpaw.core.paths import (
    AGENT_DIR,
    AGENT_MD,
    AGENT_WRITABLE_FILES,
    AGENT_YAML,
    BROWSER_COOKIES_JSON,
    CONFIG_DIR,
    CONVERSATIONS_DB,
    CRONS_DIR,
    DATA_DIR,
    DOT_ENV,
    DOWNLOADS_DIR,
    DYNAMIC_CRONS_JSON,
    HEARTBEAT_LOG_JSONL,
    HEARTBEAT_MD,
    IDENTITY_FILES,
    MEMORY_CONVERSATIONS_DIR,
    MEMORY_DIR,
    MEMORY_LOGS_DIR,
    SCREENSHOTS_DIR,
    SESSIONS_JSON,
    SKILLS_DIR,
    SOUL_MD,
    SUBAGENTS_YAML,
    TASKS_YAML,
    TEAM_DIR,
    TOKEN_USAGE_JSONL,
    TOOLS_DIR,
    UPLOADS_DIR,
    USER_MD,
    VECTORS_DB,
    WORKSPACE_DIR,
    WRITE_PROTECTED_DIRS,
)


def _all_path_constants() -> list[PurePosixPath]:
    """Collect every PurePosixPath constant exported from paths module."""
    return [
        v for v in vars(paths).values()
        if isinstance(v, PurePosixPath)
    ]


class TestConstantTypes:
    """Every path constant must be a PurePosixPath instance."""

    def test_top_level_dirs_are_pure_posix_paths(self) -> None:
        for constant in [AGENT_DIR, CONFIG_DIR, DATA_DIR, MEMORY_DIR, WORKSPACE_DIR]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_identity_files_are_pure_posix_paths(self) -> None:
        for constant in [AGENT_MD, USER_MD, SOUL_MD, HEARTBEAT_MD]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_extension_dirs_are_pure_posix_paths(self) -> None:
        for constant in [TOOLS_DIR, SKILLS_DIR, TEAM_DIR]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_config_paths_are_pure_posix_paths(self) -> None:
        for constant in [AGENT_YAML, DOT_ENV, CRONS_DIR]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_data_paths_are_pure_posix_paths(self) -> None:
        for constant in [
            CONVERSATIONS_DB,
            SESSIONS_JSON,
            SUBAGENTS_YAML,
            TOKEN_USAGE_JSONL,
            VECTORS_DB,
            BROWSER_COOKIES_JSON,
            DYNAMIC_CRONS_JSON,
            HEARTBEAT_LOG_JSONL,
            TASKS_YAML,
            UPLOADS_DIR,
        ]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_memory_paths_are_pure_posix_paths(self) -> None:
        for constant in [MEMORY_CONVERSATIONS_DIR, MEMORY_LOGS_DIR]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"

    def test_workspace_paths_are_pure_posix_paths(self) -> None:
        for constant in [DOWNLOADS_DIR, SCREENSHOTS_DIR]:
            assert isinstance(constant, PurePosixPath), f"{constant!r} is not a PurePosixPath"


class TestNoDuplicatePaths:
    """No two constants should resolve to the same path string."""

    def test_all_path_constants_are_unique(self) -> None:
        all_paths = _all_path_constants()
        path_strings = [str(p) for p in all_paths]
        assert len(path_strings) == len(set(path_strings)), (
            f"Duplicate paths found: "
            f"{[p for p in path_strings if path_strings.count(p) > 1]}"
        )


class TestIdentityFiles:
    """IDENTITY_FILES must contain exactly the four required markdown files."""

    def test_identity_files_has_four_entries(self) -> None:
        assert len(IDENTITY_FILES) == 4

    def test_identity_files_contains_agent_md(self) -> None:
        assert AGENT_MD in IDENTITY_FILES

    def test_identity_files_contains_user_md(self) -> None:
        assert USER_MD in IDENTITY_FILES

    def test_identity_files_contains_soul_md(self) -> None:
        assert SOUL_MD in IDENTITY_FILES

    def test_identity_files_contains_heartbeat_md(self) -> None:
        assert HEARTBEAT_MD in IDENTITY_FILES

    def test_identity_files_are_all_pure_posix_paths(self) -> None:
        for p in IDENTITY_FILES:
            assert isinstance(p, PurePosixPath)


class TestParentDirectoryConsistency:
    """Paths must live under their expected parent directories."""

    def test_agent_md_under_agent_dir(self) -> None:
        assert AGENT_MD.parent == AGENT_DIR

    def test_user_md_under_agent_dir(self) -> None:
        assert USER_MD.parent == AGENT_DIR

    def test_soul_md_under_agent_dir(self) -> None:
        assert SOUL_MD.parent == AGENT_DIR

    def test_heartbeat_md_under_agent_dir(self) -> None:
        assert HEARTBEAT_MD.parent == AGENT_DIR

    def test_tools_dir_under_agent_dir(self) -> None:
        assert TOOLS_DIR.parent == AGENT_DIR

    def test_skills_dir_under_agent_dir(self) -> None:
        assert SKILLS_DIR.parent == AGENT_DIR

    def test_team_dir_under_agent_dir(self) -> None:
        assert TEAM_DIR.parent == AGENT_DIR

    def test_agent_yaml_under_config_dir(self) -> None:
        assert AGENT_YAML.parent == CONFIG_DIR

    def test_dot_env_under_config_dir(self) -> None:
        assert DOT_ENV.parent == CONFIG_DIR

    def test_crons_dir_under_config_dir(self) -> None:
        assert CRONS_DIR.parent == CONFIG_DIR

    def test_conversations_db_under_data_dir(self) -> None:
        assert CONVERSATIONS_DB.parent == DATA_DIR

    def test_sessions_json_under_data_dir(self) -> None:
        assert SESSIONS_JSON.parent == DATA_DIR

    def test_subagents_yaml_under_data_dir(self) -> None:
        assert SUBAGENTS_YAML.parent == DATA_DIR

    def test_token_usage_jsonl_under_data_dir(self) -> None:
        assert TOKEN_USAGE_JSONL.parent == DATA_DIR

    def test_vectors_db_under_data_dir(self) -> None:
        assert VECTORS_DB.parent == DATA_DIR

    def test_browser_cookies_json_under_data_dir(self) -> None:
        assert BROWSER_COOKIES_JSON.parent == DATA_DIR

    def test_dynamic_crons_json_under_data_dir(self) -> None:
        assert DYNAMIC_CRONS_JSON.parent == DATA_DIR

    def test_heartbeat_log_jsonl_under_data_dir(self) -> None:
        assert HEARTBEAT_LOG_JSONL.parent == DATA_DIR

    def test_tasks_yaml_under_data_dir(self) -> None:
        assert TASKS_YAML.parent == DATA_DIR

    def test_uploads_dir_under_data_dir(self) -> None:
        assert UPLOADS_DIR.parent == DATA_DIR

    def test_memory_conversations_dir_under_memory_dir(self) -> None:
        assert MEMORY_CONVERSATIONS_DIR.parent == MEMORY_DIR

    def test_memory_logs_dir_under_memory_dir(self) -> None:
        assert MEMORY_LOGS_DIR.parent == MEMORY_DIR

    def test_downloads_dir_under_workspace_dir(self) -> None:
        assert DOWNLOADS_DIR.parent == WORKSPACE_DIR

    def test_screenshots_dir_under_workspace_dir(self) -> None:
        assert SCREENSHOTS_DIR.parent == WORKSPACE_DIR


class TestWriteProtectedDirs:
    """WRITE_PROTECTED_DIRS must be a frozenset of directory path strings."""

    def test_write_protected_dirs_is_frozenset(self) -> None:
        assert isinstance(WRITE_PROTECTED_DIRS, frozenset)

    def test_write_protected_dirs_contains_data_dir(self) -> None:
        assert str(DATA_DIR) in WRITE_PROTECTED_DIRS

    def test_write_protected_dirs_contains_config_dir(self) -> None:
        assert str(CONFIG_DIR) in WRITE_PROTECTED_DIRS

    def test_write_protected_dirs_contains_memory_logs(self) -> None:
        assert str(MEMORY_LOGS_DIR) in WRITE_PROTECTED_DIRS

    def test_write_protected_dirs_contains_memory_conversations(self) -> None:
        assert str(MEMORY_CONVERSATIONS_DIR) in WRITE_PROTECTED_DIRS

    def test_write_protected_dirs_entries_are_strings(self) -> None:
        for entry in WRITE_PROTECTED_DIRS:
            assert isinstance(entry, str), f"{entry!r} is not a string"

    def test_write_protected_dirs_entries_have_no_leading_slash(self) -> None:
        for entry in WRITE_PROTECTED_DIRS:
            assert not entry.startswith("/"), f"{entry!r} must be a relative path"


class TestAgentWritableFiles:
    """AGENT_WRITABLE_FILES must be a frozenset containing the allowed exceptions."""

    def test_agent_writable_files_is_frozenset(self) -> None:
        assert isinstance(AGENT_WRITABLE_FILES, frozenset)

    def test_agent_writable_files_contains_heartbeat_md(self) -> None:
        assert str(HEARTBEAT_MD) in AGENT_WRITABLE_FILES

    def test_agent_writable_files_entries_are_strings(self) -> None:
        for entry in AGENT_WRITABLE_FILES:
            assert isinstance(entry, str), f"{entry!r} is not a string"

    def test_agent_writable_files_entries_reference_valid_paths(self) -> None:
        all_path_strings = {str(p) for p in _all_path_constants()}
        for entry in AGENT_WRITABLE_FILES:
            assert entry in all_path_strings, (
                f"{entry!r} in AGENT_WRITABLE_FILES does not match any known path constant"
            )

    def test_agent_writable_files_entries_have_no_leading_slash(self) -> None:
        for entry in AGENT_WRITABLE_FILES:
            assert not entry.startswith("/"), f"{entry!r} must be a relative path"
