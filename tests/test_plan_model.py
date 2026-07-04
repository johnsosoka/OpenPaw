"""Tests for the Plan model (ultra harness state, ADR-101 §3)."""

from openpaw.model.plan import IdeationResult, Plan, PlanStep, StepStatus


def make_plan(n: int = 3) -> Plan:
    return Plan(
        objective="test objective",
        steps=tuple(PlanStep(id=str(i + 1), description=f"step {i + 1}") for i in range(n)),
    )


class TestPlanProgression:
    def test_next_pending_returns_first_pending(self) -> None:
        plan = make_plan().with_step_status("1", StepStatus.DONE)
        nxt = plan.next_pending()
        assert nxt is not None and nxt.id == "2"

    def test_complete_when_no_pending(self) -> None:
        plan = make_plan(1).with_step_status("1", StepStatus.DONE)
        assert plan.is_complete()
        assert plan.next_pending() is None

    def test_skipped_and_failed_are_not_pending(self) -> None:
        plan = (
            make_plan(2)
            .with_step_status("1", StepStatus.SKIPPED)
            .with_step_status("2", StepStatus.FAILED)
        )
        assert plan.is_complete()

    def test_status_update_preserves_other_steps_and_revision(self) -> None:
        plan = make_plan()
        updated = plan.with_step_status("2", StepStatus.DONE, "did it")
        assert updated.get_step("2").status == StepStatus.DONE  # type: ignore[union-attr]
        assert updated.get_step("2").result_summary == "did it"  # type: ignore[union-attr]
        assert updated.get_step("1").status == StepStatus.PENDING  # type: ignore[union-attr]
        assert updated.revision == plan.revision  # status change is not structural


class TestPlanRevision:
    def test_insertion_slots_after_anchor(self) -> None:
        plan = make_plan().with_insertion("2", "inserted work")
        ids = [s.id for s in plan.steps]
        assert ids == ["1", "2", "2A", "3"]
        assert plan.revision == 1

    def test_nested_insertion(self) -> None:
        plan = make_plan().with_insertion("2", "a").with_insertion("2A", "b")
        ids = [s.id for s in plan.steps]
        assert ids == ["1", "2", "2A", "2AA", "3"]

    def test_remaining_replaced_preserves_executed(self) -> None:
        plan = make_plan().with_step_status("1", StepStatus.DONE)
        new_tail = (PlanStep(id="R1", description="new path"),)
        revised = plan.with_remaining_replaced(new_tail)
        assert [s.id for s in revised.steps] == ["1", "R1"]
        assert revised.get_step("1").status == StepStatus.DONE  # type: ignore[union-attr]
        assert revised.revision == 1


class TestPlanSerialization:
    def test_payload_shape(self) -> None:
        payload = make_plan(2).to_payload()
        assert payload["objective"] == "test objective"
        assert payload["revision"] == 0
        steps = payload["steps"]
        assert isinstance(steps, list) and len(steps) == 2
        assert steps[0] == {"id": "1", "description": "step 1", "status": "pending"}

    def test_render_checklist_marks(self) -> None:
        plan = (
            make_plan()
            .with_step_status("1", StepStatus.DONE)
            .with_step_status("2", StepStatus.IN_PROGRESS)
        )
        text = plan.render_checklist()
        assert "[x] 1." in text
        assert "[~] 2." in text
        assert "[ ] 3." in text


def test_ideation_result_defaults() -> None:
    r = IdeationResult(ideas=("a", "b"))
    assert r.evaluations == () and r.recommended_directions == ()
