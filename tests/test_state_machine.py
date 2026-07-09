"""Test AgentOS StateMachine — agent lifecycle FSM with guards and timeouts."""

from __future__ import annotations

import time

import pytest

from agentos.core.state_machine import (
    VALID_TRANSITIONS,
    AgentState,
    AgentStateMachine,
    StateMachineConfig,
    StateTimeoutError,
    StateTransition,
    TransitionError,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sm():
    """Fresh state machine per test."""
    return AgentStateMachine()


@pytest.fixture
def sm_strict():
    """State machine with tight timeout config."""
    return AgentStateMachine(StateMachineConfig(
        max_thinking_time=0.001,
        max_acting_time=0.001,
        max_transitions=5,
        auto_recover=False,
    ))


# ============================================================================
# StateTransition & Config
# ============================================================================

class TestStateTransition:
    def test_creation_defaults(self):
        t = StateTransition(AgentState.IDLE, AgentState.INITIALIZING, reason="boot")
        assert t.from_state == AgentState.IDLE
        assert t.to_state == AgentState.INITIALIZING
        assert t.reason == "boot"
        assert isinstance(t.timestamp, float)
        assert t.metadata == {}

    def test_creation_with_metadata(self):
        t = StateTransition(AgentState.THINKING, AgentState.ACTING, metadata={"tool": "search"})
        assert t.metadata["tool"] == "search"


class TestStateMachineConfig:
    def test_defaults(self):
        cfg = StateMachineConfig()
        assert cfg.max_thinking_time == 300.0
        assert cfg.max_total_time == 3600.0
        assert cfg.max_transitions == 500
        assert cfg.auto_recover is True

    def test_custom(self):
        cfg = StateMachineConfig(max_thinking_time=10.0, max_retries_after_error=2)
        assert cfg.max_thinking_time == 10.0
        assert cfg.max_retries_after_error == 2


# ============================================================================
# VALID_TRANSITIONS table
# ============================================================================

class TestValidTransitions:
    def test_terminal_states_no_exits(self):
        assert VALID_TRANSITIONS[AgentState.COMPLETED] == set()

    def test_idle_can_init_or_cancel(self):
        assert AgentState.INITIALIZING in VALID_TRANSITIONS[AgentState.IDLE]
        assert AgentState.CANCELLED in VALID_TRANSITIONS[AgentState.IDLE]

    def test_thinking_can_act_complete_fail(self):
        targets = VALID_TRANSITIONS[AgentState.THINKING]
        assert AgentState.ACTING in targets
        assert AgentState.COMPLETED in targets
        assert AgentState.FAILED in targets

    def test_failed_can_idle_or_error(self):
        targets = VALID_TRANSITIONS[AgentState.FAILED]
        assert AgentState.IDLE in targets
        assert AgentState.ERROR in targets


# ============================================================================
# Initial state & properties
# ============================================================================

class TestInitialState:
    def test_starts_idle(self, sm):
        assert sm.state == AgentState.IDLE

    def test_history_empty(self, sm):
        assert sm.history == []

    def test_elapsed_increases(self, sm):
        e1 = sm.elapsed_total
        time.sleep(0.02)
        assert sm.elapsed_total > e1

    def test_summary_at_idle(self, sm):
        s = sm.summary()
        assert s["state"] == "idle"
        assert s["transitions"] == 0
        assert s["error_count"] == 0
        assert s["is_active"] is False
        assert s["is_terminal"] is False


# ============================================================================
# Valid transitions
# ============================================================================

class TestValidTransitionsFlow:
    def test_start_initializing(self, sm):
        t = sm.start("boot")
        assert sm.state == AgentState.INITIALIZING
        assert t.from_state == AgentState.IDLE
        assert t.to_state == AgentState.INITIALIZING
        assert len(sm.history) == 1

    def test_full_happy_path(self, sm):
        sm.start()
        sm.think()
        sm.act()
        sm.observe()
        sm.think()
        sm.complete()
        assert sm.state == AgentState.COMPLETED
        assert len(sm.history) == 6  # 5 transitions → 6 entries? No, 6 transitions
        assert sm.is_terminal()

    def test_think_to_complete(self, sm):
        sm.start()
        sm.think()
        sm.complete()
        assert sm.state == AgentState.COMPLETED

    def test_fail_from_thinking(self, sm):
        sm.start()
        sm.think()
        sm.fail("model error")
        assert sm.state == AgentState.FAILED

    def test_pause_and_resume(self, sm):
        sm.start()
        sm.think()
        sm.pause("user request")
        assert sm.state == AgentState.PAUSED
        sm.resume("user said go")
        assert sm.state == AgentState.THINKING

    def test_cancel_from_waiting(self, sm):
        sm.start()
        sm.think()
        sm.transition(AgentState.WAITING, "human needed")
        sm.cancel("abort")
        assert sm.state == AgentState.CANCELLED

    def test_run_idle_from_failed(self, sm):
        sm.start()
        sm.think()
        sm.fail()
        sm.run_idle()
        assert sm.state == AgentState.IDLE

    def test_run_idle_from_error(self, sm):
        sm.start()
        sm.think()
        sm.error()
        sm.run_idle()
        assert sm.state == AgentState.IDLE

    def test_is_active(self, sm):
        assert not sm.is_active()
        sm.start()
        sm.think()
        assert sm.is_active()
        sm.complete()
        assert not sm.is_active()

    def test_error_increments_count(self, sm):
        sm.start()
        sm.think()
        sm.error("oops")
        assert sm.summary()["error_count"] == 1
        sm.run_idle()
        sm.start()
        sm.think()
        sm.fail("again")
        assert sm.summary()["error_count"] == 2


# ============================================================================
# Invalid transitions
# ============================================================================

class TestInvalidTransitions:
    def test_idle_to_thinking_raises(self, sm):
        with pytest.raises(TransitionError, match="idle → thinking"):
            sm.think()

    def test_acting_to_init_raises(self, sm):
        sm.start()
        sm.think()
        sm.act()
        with pytest.raises(TransitionError):
            sm.start()

    def test_complete_is_terminal(self, sm):
        sm.start()
        sm.think()
        sm.complete()
        with pytest.raises(TransitionError):
            sm.think()

    def test_failed_cannot_think(self, sm):
        sm.start()
        sm.think()
        sm.fail()
        with pytest.raises(TransitionError):
            sm.think()

    def test_resume_from_non_paused_raises(self, sm):
        sm.start()
        sm.think()
        with pytest.raises(TransitionError):
            sm.resume()

    def test_run_idle_from_running_raises(self, sm):
        sm.start()
        sm.think()
        with pytest.raises(TransitionError):
            sm.run_idle()


# ============================================================================
# Timeouts
# ============================================================================

class TestTimeouts:
    def test_thinking_timeout_raises(self, sm_strict):
        sm_strict.start()
        sm_strict.think()
        with pytest.raises(StateTimeoutError):
            time.sleep(0.005)
            sm_strict.act()

    def test_acting_timeout_raises(self, sm_strict):
        sm_strict.start()
        sm_strict.think()
        sm_strict.act()
        with pytest.raises(StateTimeoutError):
            time.sleep(0.005)
            sm_strict.observe()

    def test_max_transitions_exceeded(self):
        sm = AgentStateMachine(StateMachineConfig(max_transitions=8))
        sm.start()
        with pytest.raises(RuntimeError, match="Max transitions"):
            for _ in range(4):
                sm.think()
                sm.act()
                sm.observe()

    def test_total_time_exceeded(self):
        sm = AgentStateMachine(StateMachineConfig(max_total_time=0.001))
        time.sleep(0.005)
        with pytest.raises(StateTimeoutError, match="timeout"):
            sm.start()


# ============================================================================
# Transition hooks
# ============================================================================

class TestHooks:
    def test_hook_fires_on_transition(self, sm):
        fired = []

        @sm.on_transition(AgentState.IDLE, AgentState.INITIALIZING)
        def on_boot(t: StateTransition):
            fired.append(t.reason)

        sm.start("booting up")
        assert fired == ["booting up"]

    def test_hook_does_not_fire_on_other_transition(self, sm):
        fired = []

        @sm.on_transition(AgentState.IDLE, AgentState.INITIALIZING)
        def on_boot(t):
            fired.append(1)

        sm.start()
        sm.think()  # different transition
        assert len(fired) == 1

    def test_multiple_hooks_same_key(self, sm):
        results = []

        @sm.on_transition(AgentState.THINKING, AgentState.ACTING)
        def h1(t): results.append("h1")

        @sm.on_transition(AgentState.THINKING, AgentState.ACTING)
        def h2(t): results.append("h2")

        sm.start()
        sm.think()
        sm.act()
        assert results == ["h1", "h2"]

    def test_hook_receives_full_transition(self, sm):
        captured = {}

        @sm.on_transition(AgentState.THINKING, AgentState.COMPLETED)
        def capture(t: StateTransition):
            captured["from"] = t.from_state.value
            captured["to"] = t.to_state.value
            captured["reason"] = t.reason

        sm.start()
        sm.think()
        sm.complete("all done")
        assert captured == {"from": "thinking", "to": "completed", "reason": "all done"}


# ============================================================================
# Convenience methods coverage
# ============================================================================

class TestConvenienceMethods:
    def test_transition_with_metadata(self, sm):
        sm.transition(AgentState.INITIALIZING, metadata={"version": "2.0"})
        assert sm.history[0].metadata == {"version": "2.0"}

    def test_observe_method(self, sm):
        sm.start()
        sm.think()
        sm.act()
        sm.observe("got results")
        assert sm.state == AgentState.OBSERVING

    def test_cancel_method(self, sm):
        sm.cancel("user aborted")
        assert sm.state == AgentState.CANCELLED

    def test_error_method(self, sm):
        sm.start()
        sm.think()
        sm.error("panic")
        assert sm.state == AgentState.ERROR

    def test_full_path_to_error_then_idle(self, sm):
        sm.start()
        sm.think()
        sm.error("oops")
        sm.run_idle()
        sm.start()
        sm.think()
        sm.complete()
        assert sm.state == AgentState.COMPLETED
        assert len(sm.history) == 7

    def test_summary_properties(self, sm):
        sm.start()
        sm.think()
        s = sm.summary()
        assert s["state"] == "thinking"
        assert s["is_active"] is True
        assert s["is_terminal"] is False

    def test_history_is_copy(self, sm):
        sm.start()
        h = sm.history
        h.pop()
        assert len(sm.history) == 1  # original unchanged

    def test_elapsed_in_state_resets_on_transition(self, sm):
        sm.start()
        e1 = sm.elapsed_in_state
        sm.think()
        time.sleep(0.01)
        sm.act()
        assert sm.elapsed_in_state < sm.elapsed_total
