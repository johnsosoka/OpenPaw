"""Tests for SubAgentStore."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpaw.stores.subagent import SubAgentStore, create_subagent_request
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus


def test_create_subagent_request(tmp_path: Path):
    """Test creating a sub-agent request and verifying persistence."""
    store = SubAgentStore(tmp_path)

    request = SubAgentRequest(
        id="req-123",
        task="Research topic X",
        label="research-x",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )

    store.create(request)

    # Verify retrieval
    retrieved = store.get("req-123")
    assert retrieved is not None
    assert retrieved.id == "req-123"
    assert retrieved.task == "Research topic X"
    assert retrieved.label == "research-x"
    assert retrieved.status == SubAgentStatus.PENDING
    assert retrieved.session_key == "telegram:12345"


def test_create_duplicate_id_raises_error(tmp_path: Path):
    """Test creating a request with duplicate ID raises ValueError."""
    store = SubAgentStore(tmp_path)

    request = SubAgentRequest(
        id="req-123",
        task="Task A",
        label="task-a",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )

    store.create(request)

    # Try to create another with same ID
    duplicate = SubAgentRequest(
        id="req-123",
        task="Task B",
        label="task-b",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )

    with pytest.raises(ValueError, match="already exists"):
        store.create(duplicate)


def test_update_status(tmp_path: Path):
    """Test updating request status."""
    store = SubAgentStore(tmp_path)

    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )

    store.create(request)

    # Update to running
    now = datetime.now(UTC)
    success = store.update_status("req-123", SubAgentStatus.RUNNING, started_at=now)
    assert success is True

    # Verify update
    updated = store.get("req-123")
    assert updated is not None
    assert updated.status == SubAgentStatus.RUNNING
    assert updated.started_at == now


def test_update_status_nonexistent_request(tmp_path: Path):
    """Test updating nonexistent request returns False."""
    store = SubAgentStore(tmp_path)

    success = store.update_status("nonexistent", SubAgentStatus.RUNNING)
    assert success is False


def test_save_result(tmp_path: Path):
    """Test saving sub-agent result."""
    store = SubAgentStore(tmp_path)

    # Create request first
    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345"
    )
    store.create(request)

    # Save result
    result = SubAgentResult(
        request_id="req-123",
        output="Here are the findings...",
        token_count=1500,
        duration_ms=5400.0
    )

    success = store.save_result(result)
    assert success is True

    # Verify retrieval
    retrieved = store.get_result("req-123")
    assert retrieved is not None
    assert retrieved.request_id == "req-123"
    assert retrieved.output == "Here are the findings..."
    assert retrieved.token_count == 1500
    assert retrieved.duration_ms == 5400.0
    assert retrieved.error is None


def test_save_result_nonexistent_request(tmp_path: Path):
    """Test saving result for nonexistent request returns False."""
    store = SubAgentStore(tmp_path)

    result = SubAgentResult(
        request_id="nonexistent",
        output="Output",
        token_count=100
    )

    success = store.save_result(result)
    assert success is False


def test_save_result_truncation(tmp_path: Path):
    """Test result output is truncated when exceeding MAX_RESULT_SIZE."""
    store = SubAgentStore(tmp_path)

    # Create request
    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345"
    )
    store.create(request)

    # Create result with large output (60K chars > 50K limit)
    large_output = "x" * 60_000
    result = SubAgentResult(
        request_id="req-123",
        output=large_output,
        token_count=1000
    )

    store.save_result(result)

    # Verify truncation
    retrieved = store.get_result("req-123")
    assert retrieved is not None
    assert len(retrieved.output) <= store.MAX_RESULT_SIZE + 100  # Allow for truncation message
    assert "[Output truncated]" in retrieved.output


def test_get_nonexistent_request(tmp_path: Path):
    """Test getting nonexistent request returns None."""
    store = SubAgentStore(tmp_path)

    request = store.get("nonexistent")
    assert request is None


def test_get_result_nonexistent(tmp_path: Path):
    """Test getting nonexistent result returns None."""
    store = SubAgentStore(tmp_path)

    result = store.get_result("nonexistent")
    assert result is None


def test_list_active_returns_only_pending_running(tmp_path: Path):
    """Test list_active returns only pending and running requests."""
    store = SubAgentStore(tmp_path)

    # Create requests with different statuses
    requests = [
        SubAgentRequest(
            id="req-1",
            task="Task 1",
            label="task-1",
            status=SubAgentStatus.PENDING,
            session_key="telegram:12345"
        ),
        SubAgentRequest(
            id="req-2",
            task="Task 2",
            label="task-2",
            status=SubAgentStatus.RUNNING,
            session_key="telegram:12345"
        ),
        SubAgentRequest(
            id="req-3",
            task="Task 3",
            label="task-3",
            status=SubAgentStatus.COMPLETED,
            session_key="telegram:12345"
        ),
        SubAgentRequest(
            id="req-4",
            task="Task 4",
            label="task-4",
            status=SubAgentStatus.FAILED,
            session_key="telegram:12345"
        ),
    ]

    for req in requests:
        store.create(req)

    # List active
    active = store.list_active()

    assert len(active) == 2
    assert {r.id for r in active} == {"req-1", "req-2"}
    assert all(r.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING) for r in active)


def test_list_recent_sorted_by_created_at(tmp_path: Path):
    """Test list_recent returns requests sorted by created_at desc."""
    store = SubAgentStore(tmp_path)

    # Create requests with different timestamps
    now = datetime.now(UTC)
    requests = [
        SubAgentRequest(
            id="req-1",
            task="Task 1",
            label="task-1",
            status=SubAgentStatus.COMPLETED,
            session_key="telegram:12345",
            created_at=now - timedelta(hours=3)
        ),
        SubAgentRequest(
            id="req-2",
            task="Task 2",
            label="task-2",
            status=SubAgentStatus.PENDING,
            session_key="telegram:12345",
            created_at=now - timedelta(hours=1)
        ),
        SubAgentRequest(
            id="req-3",
            task="Task 3",
            label="task-3",
            status=SubAgentStatus.RUNNING,
            session_key="telegram:12345",
            created_at=now
        ),
    ]

    for req in requests:
        store.create(req)

    # List recent
    recent = store.list_recent(limit=10)

    assert len(recent) == 3
    # Should be sorted newest first
    assert recent[0].id == "req-3"
    assert recent[1].id == "req-2"
    assert recent[2].id == "req-1"


def test_list_recent_respects_limit(tmp_path: Path):
    """Test list_recent respects limit parameter."""
    store = SubAgentStore(tmp_path)

    # Create 5 requests
    for i in range(5):
        request = SubAgentRequest(
            id=f"req-{i}",
            task=f"Task {i}",
            label=f"task-{i}",
            status=SubAgentStatus.COMPLETED,
            session_key="telegram:12345"
        )
        store.create(request)

    # List with limit
    recent = store.list_recent(limit=3)

    assert len(recent) == 3


def test_cleanup_stale_removes_old_records(tmp_path: Path):
    """Test cleanup_stale removes completed records older than max_age_hours."""
    store = SubAgentStore(tmp_path, max_age_hours=1)

    now = datetime.now(UTC)

    # Create old completed request (2 hours ago)
    old_request = SubAgentRequest(
        id="req-old",
        task="Old task",
        label="old",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        created_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=2)
    )
    store.create(old_request)

    # Create recent completed request (30 minutes ago)
    recent_request = SubAgentRequest(
        id="req-recent",
        task="Recent task",
        label="recent",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        created_at=now - timedelta(minutes=30),
        completed_at=now - timedelta(minutes=30)
    )
    store.create(recent_request)

    # Cleanup
    removed = store.cleanup_stale()

    # Old request should be removed, recent should remain
    assert removed == 1
    assert store.get("req-old") is None
    assert store.get("req-recent") is not None


def test_cleanup_stale_marks_stale_running_as_failed(tmp_path: Path):
    """Test cleanup_stale marks stale running/pending requests as timed_out."""
    # Create store without auto-cleanup to manually control when it runs
    store = SubAgentStore(tmp_path, max_age_hours=24)

    now = datetime.now(UTC)

    # Create running request past its timeout (created 45 minutes ago, timeout 30 minutes)
    stale_request = SubAgentRequest(
        id="req-stale",
        task="Stale task",
        label="stale",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        created_at=now - timedelta(minutes=45),
        timeout_minutes=30
    )
    store.create(stale_request)

    # Create running request within timeout
    active_request = SubAgentRequest(
        id="req-active",
        task="Active task",
        label="active",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        created_at=now - timedelta(minutes=10),
        timeout_minutes=30
    )
    store.create(active_request)

    # Manually call cleanup (note: cleanup is also called in __init__ but after these creates)
    removed = store.cleanup_stale()

    # Stale request should be marked as timed_out
    stale = store.get("req-stale")
    assert stale is not None
    assert stale.status == SubAgentStatus.TIMED_OUT
    assert stale.completed_at is not None

    # Active request should remain running
    active = store.get("req-active")
    assert active is not None
    assert active.status == SubAgentStatus.RUNNING


def test_cleanup_stale_removes_orphaned_results(tmp_path: Path):
    """Test cleanup_stale removes results for deleted requests."""
    store = SubAgentStore(tmp_path, max_age_hours=1)

    now = datetime.now(UTC)

    # Create old completed request with result
    old_request = SubAgentRequest(
        id="req-old",
        task="Old task",
        label="old",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        created_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=2)
    )
    store.create(old_request)

    result = SubAgentResult(
        request_id="req-old",
        output="Old output",
        token_count=100
    )
    store.save_result(result)

    # Cleanup (should remove old request and its result)
    store.cleanup_stale()

    assert store.get("req-old") is None
    assert store.get_result("req-old") is None


def test_thread_safety_concurrent_writes(tmp_path: Path):
    """Test store handles concurrent writes without corruption."""
    store = SubAgentStore(tmp_path)

    def create_requests(start_id: int, count: int):
        for i in range(count):
            request = SubAgentRequest(
                id=f"req-{start_id}-{i}",
                task=f"Task {start_id}-{i}",
                label=f"task-{start_id}-{i}",
                status=SubAgentStatus.PENDING,
                session_key="telegram:12345"
            )
            store.create(request)

    # Create threads
    threads = []
    for i in range(3):
        thread = threading.Thread(target=create_requests, args=(i, 5))
        threads.append(thread)
        thread.start()

    # Wait for completion
    for thread in threads:
        thread.join()

    # Verify all requests were created
    recent = store.list_recent(limit=100)
    assert len(recent) == 15


def test_request_to_dict_from_dict_roundtrip(tmp_path: Path):
    """Test SubAgentRequest serialization roundtrip."""
    now = datetime.now(UTC)

    original = SubAgentRequest(
        id="req-123",
        task="Research topic X",
        label="research-x",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        created_at=now - timedelta(hours=1),
        started_at=now - timedelta(minutes=50),
        completed_at=now - timedelta(minutes=10),
        timeout_minutes=60,
        notify=True
    )

    # Roundtrip
    data = original.to_dict()
    restored = SubAgentRequest.from_dict(data)

    assert restored.id == original.id
    assert restored.task == original.task
    assert restored.label == original.label
    assert restored.status == original.status
    assert restored.session_key == original.session_key
    assert restored.created_at == original.created_at
    assert restored.started_at == original.started_at
    assert restored.completed_at == original.completed_at
    assert restored.timeout_minutes == original.timeout_minutes
    assert restored.notify == original.notify


def test_result_to_dict_from_dict_roundtrip(tmp_path: Path):
    """Test SubAgentResult serialization roundtrip."""
    original = SubAgentResult(
        request_id="req-123",
        output="Here are the findings...",
        token_count=1500,
        duration_ms=5400.0,
        error=None
    )

    # Roundtrip
    data = original.to_dict()
    restored = SubAgentResult.from_dict(data)

    assert restored.request_id == original.request_id
    assert restored.output == original.output
    assert restored.token_count == original.token_count
    assert restored.duration_ms == original.duration_ms
    assert restored.error == original.error


def test_storage_file_does_not_exist_yet(tmp_path: Path):
    """Test store handles nonexistent storage file gracefully."""
    store = SubAgentStore(tmp_path)

    # Should not crash
    requests = store.list_recent()
    assert len(requests) == 0


def test_openpaw_directory_created(tmp_path: Path):
    """Test SubAgentStore creates data directory."""
    store = SubAgentStore(tmp_path)

    data_dir = tmp_path / "data"
    assert data_dir.exists()
    assert data_dir.is_dir()


def test_persistence_survives_reload(tmp_path: Path):
    """Test YAML persistence survives store reload."""
    # Create store and request
    store1 = SubAgentStore(tmp_path)

    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )
    store1.create(request)

    # Create new store instance (simulates restart)
    store2 = SubAgentStore(tmp_path)

    # Should load same request
    retrieved = store2.get("req-123")
    assert retrieved is not None
    assert retrieved.id == "req-123"
    assert retrieved.task == "Task"


def test_result_with_error(tmp_path: Path):
    """Test saving result with error message."""
    store = SubAgentStore(tmp_path)

    # Create request
    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345"
    )
    store.create(request)

    # Save result with error
    result = SubAgentResult(
        request_id="req-123",
        output="",
        token_count=0,
        duration_ms=100.0,
        error="Timeout error"
    )

    store.save_result(result)

    # Verify error persisted
    retrieved = store.get_result("req-123")
    assert retrieved is not None
    assert retrieved.error == "Timeout error"


def test_create_subagent_request_factory(tmp_path: Path):
    """Test create_subagent_request factory function."""
    request = create_subagent_request(
        task="Research topic X",
        label="research-x",
        session_key="telegram:12345",
        timeout_minutes=60,
        notify=True
    )

    assert request.id is not None
    assert len(request.id) > 0  # Should be a UUID
    assert request.task == "Research topic X"
    assert request.label == "research-x"
    assert request.status == SubAgentStatus.PENDING
    assert request.session_key == "telegram:12345"
    assert request.timeout_minutes == 60
    assert request.notify is True


def test_update_status_with_additional_kwargs(tmp_path: Path):
    """Test update_status accepts additional kwargs."""
    store = SubAgentStore(tmp_path)

    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345"
    )
    store.create(request)

    # Update with additional fields
    now = datetime.now(UTC)
    store.update_status(
        "req-123",
        SubAgentStatus.COMPLETED,
        completed_at=now,
        notify=False
    )

    # Verify updates
    updated = store.get("req-123")
    assert updated is not None
    assert updated.status == SubAgentStatus.COMPLETED
    assert updated.completed_at == now
    assert updated.notify is False


def test_cleanup_stale_called_on_init(tmp_path: Path):
    """Test cleanup_stale is called during initialization."""
    now = datetime.now(UTC)

    # Create store and add old completed request
    store1 = SubAgentStore(tmp_path, max_age_hours=1)

    old_request = SubAgentRequest(
        id="req-old",
        task="Old task",
        label="old",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        created_at=now - timedelta(hours=3),
        completed_at=now - timedelta(hours=3)
    )
    store1.create(old_request)

    # Create new store instance (should cleanup on init)
    store2 = SubAgentStore(tmp_path, max_age_hours=1)

    # Old request should be gone
    assert store2.get("req-old") is None


def test_save_result_replaces_existing(tmp_path: Path):
    """Test saving result replaces existing result for same request."""
    store = SubAgentStore(tmp_path)

    # Create request
    request = SubAgentRequest(
        id="req-123",
        task="Task",
        label="task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345"
    )
    store.create(request)

    # Save first result
    result1 = SubAgentResult(
        request_id="req-123",
        output="First output",
        token_count=100
    )
    store.save_result(result1)

    # Save second result (should replace)
    result2 = SubAgentResult(
        request_id="req-123",
        output="Second output",
        token_count=200
    )
    store.save_result(result2)

    # Verify only second result exists
    retrieved = store.get_result("req-123")
    assert retrieved is not None
    assert retrieved.output == "Second output"
    assert retrieved.token_count == 200
