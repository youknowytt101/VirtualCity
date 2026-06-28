"""Explicit pipeline state machine for the WorldBuilder orchestrator.

This is a pure, side-effect-free transition table. The orchestrator drives it
and persists each transition through pipeline_state; the machine itself never
touches disk. Keeping the legal (state, event) -> new_state map in one place
makes illegal jumps (e.g. acquire failed but cook still runs) impossible by
construction instead of relying on scattered if/return ordering.
"""
from __future__ import annotations

from typing import Iterable


# 管线生命周期的有限状态，与真相源里的 phase 解耦：phase 记录"在做哪一步"，
# 这里记录"流程走到哪个阶段"，由编排器把状态映射成落盘的 phase。
QUEUED = "queued"
ACQUIRING = "acquiring"
REFINING = "refining"
COOKING = "cooking"
# QA：仅指"流程编排走到 QA 这一段"，不代表质量裁决结论。质量好坏（pass/warn/
# fail，及是否需人工复核）由 export_gate 读 run.qa 独立判定，不在本状态机表达。
QA = "qa"
DONE = "done"
FAILED = "failed"

TERMINAL_STATES = frozenset({DONE, FAILED})

# 推进事件：每个事件把流程从一个阶段带到下一个阶段。
START = "start"
ACQUIRED = "acquired"
REFINED = "refined"
COOKED = "cooked"
# QA_PASSED：语义是"recook 进程成功退出、流程可离开 QA 段"，等价于
# "COOK_VERIFIED"，并非"模型质量评分通过"。质量裁决见 export_gate。
QA_PASSED = "qa_passed"
FAIL = "fail"

# (state, event) -> new_state。只列合法转移；fail 由 transition 统一处理，
# 不在表里逐条铺开，避免 N 个状态各写一行 fail。
_TRANSITIONS: dict[tuple[str, str], str] = {
    (QUEUED, START): ACQUIRING,
    (ACQUIRING, ACQUIRED): REFINING,
    (REFINING, REFINED): COOKING,
    (COOKING, COOKED): QA,
    (QA, QA_PASSED): DONE,
}


class IllegalTransition(ValueError):
    """Raised when an (state, event) pair has no legal target."""


def transition(state: str, event: str) -> str:
    """Pure transition: return the next state for (state, event).

    fail from any non-terminal state goes to FAILED. Terminal states accept no
    further events. Any other unlisted pair is illegal and raises, so an
    out-of-order event (e.g. COOKED before ACQUIRED) can never silently advance.
    """
    if state in TERMINAL_STATES:
        raise IllegalTransition(f"{state} is terminal; event {event!r} rejected")
    if event == FAIL:
        return FAILED
    try:
        return _TRANSITIONS[(state, event)]
    except KeyError:
        raise IllegalTransition(f"no transition for state={state!r} event={event!r}")


def run(events: Iterable[str], *, start: str = QUEUED) -> str:
    """Fold a sequence of events over the machine, returning the final state.

    Convenience for tests and for driving a full run from an event log.
    """
    state = start
    for event in events:
        state = transition(state, event)
    return state


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
