from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class RunState(StrEnum):
    INPUTS_FROZEN = "INPUTS_FROZEN"
    RUNNING = "RUNNING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    CROSS_EXAMINING = "CROSS_EXAMINING"
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


_TERMINAL = {RunState.ACCEPTED, RunState.REJECTED, RunState.CANCELLED}
_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.INPUTS_FROZEN: {RunState.RUNNING, RunState.CANCELLED},
    RunState.RUNNING: {RunState.READY_FOR_REVIEW, RunState.BLOCKED, RunState.CANCELLED},
    RunState.BLOCKED: {RunState.RUNNING, RunState.CANCELLED},
    RunState.READY_FOR_REVIEW: {
        RunState.ACCEPTED,
        RunState.REJECTED,
        RunState.CROSS_EXAMINING,
        RunState.CANCELLED,
    },
    RunState.CROSS_EXAMINING: {RunState.READY_FOR_REVIEW, RunState.BLOCKED, RunState.CANCELLED},
    RunState.ACCEPTED: set(),
    RunState.REJECTED: set(),
    RunState.CANCELLED: set(),
}


@dataclass(frozen=True)
class WorkflowSpec:
    analyst_count: int = 1
    max_attempts_per_job: int = 2
    max_cross_exam_rounds: int = 1
    max_cost_usd: str = "20"

    def __post_init__(self) -> None:
        if self.analyst_count not in {1, 2}:
            raise ValueError("v0.5 allows one baseline analyst and at most one challenger")
        if not (1 <= self.max_attempts_per_job <= 3):
            raise ValueError("attempt budget outside allowed range")
        if self.max_cross_exam_rounds not in {0, 1}:
            raise ValueError("cross-examination must remain bounded")


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    state: RunState
    input_hash: str
    analyst_count: int
    completed_first_passes: int = 0
    cross_exam_rounds: int = 0
    revision: int = 1

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL


def transition(run: ResearchRun, target: RunState) -> ResearchRun:
    if target not in _ALLOWED[run.state]:
        raise ValueError(f"illegal transition {run.state} -> {target}")
    if run.terminal:
        raise ValueError("terminal run cannot be reopened; create a new run")
    if target is RunState.READY_FOR_REVIEW and run.completed_first_passes != run.analyst_count:
        raise ValueError("all blind first passes must complete before review")
    if target is RunState.CROSS_EXAMINING and run.cross_exam_rounds >= 1:
        raise ValueError("cross-examination budget exhausted")
    rounds = run.cross_exam_rounds + (1 if target is RunState.CROSS_EXAMINING else 0)
    return replace(run, state=target, cross_exam_rounds=rounds, revision=run.revision + 1)


def record_first_pass(run: ResearchRun) -> ResearchRun:
    if run.state is not RunState.RUNNING:
        raise ValueError("first-pass results may only arrive while RUNNING")
    if run.completed_first_passes >= run.analyst_count:
        raise ValueError("too many first-pass results")
    return replace(
        run,
        completed_first_passes=run.completed_first_passes + 1,
        revision=run.revision + 1,
    )


def blind_peer_visible(run: ResearchRun) -> bool:
    """First-pass peer opinions remain sealed until explicit cross-examination."""
    return run.state is RunState.CROSS_EXAMINING
