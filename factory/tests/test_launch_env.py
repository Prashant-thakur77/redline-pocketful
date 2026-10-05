from factory import launch


def test_seats_never_leave_commands_running_after_their_turn():
    """Regression: seats ran gate suites in the background, ended the turn with no reply, and the
    report written when the run finished never reached the room (stage 2, N2-1)."""
    assert launch.FOREGROUND["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert int(launch.FOREGROUND["BASH_MAX_TIMEOUT_MS"]) >= 40 * 60 * 1000  # a full close run fits


def test_a_turn_outlasts_the_longest_foreground_command():
    """Regression: with background commands off, the builder's build-and-gate turn passed the
    one-hour turn limit and was cut off mid-work (stage 2, N2-4)."""
    from factory.seat import CLAUDE_TURN_S
    assert CLAUDE_TURN_S * 1000 > int(launch.FOREGROUND["BASH_MAX_TIMEOUT_MS"])
