from factory.watchdog import limit_failures


def test_only_limit_failures_are_picked_up():
    lines = [
        "2026-10-04 15:47:36 WARNING band.platform.message_lifecycle: Marking message m1 as failed: "
        "Claude AI usage limit reached, resets at 5pm",
        "2026-10-04 15:48:00 WARNING band.platform.message_lifecycle: Marking message m2 as failed: "
        "Claude SDK finished a turn without calling band_send_message",
        "2026-10-04 15:49:00 WARNING band.platform.message_lifecycle: Marking message m3 as failed: "
        "API Error: 429 rate_limit_error",
        "unrelated line",
    ]
    assert [m for m, _ in limit_failures(lines)] == ["m1", "m2", "m3"]


def test_hung_resync_is_detected_but_work_resets_the_count():
    from factory.watchdog import STUCK_AFTER, stuck_on
    line = "INFO band.runtime.execution: ExecutionContext r: Catching up missed message abc via /next resync"
    streak = {}
    assert stuck_on([line] * (STUCK_AFTER - 1) + ["INFO ...: Tool call: Bash"] + [line] * 5, streak) is None
    assert stuck_on([line] * STUCK_AFTER, {}) == "abc"


def test_a_commit_the_room_never_heard_about_is_flagged_after_quiet_time():
    """Regression: the verifier committed its stage-1 close verdict but its message never
    reached the room, and the run sat silent with nobody told."""
    from factory.seats import load_seats
    from factory.watchdog import UNREPORTED_AFTER, last_send_time, unreported
    seats = load_seats()
    sent = last_send_time(["2026-10-04 21:45:17,987 INFO x: Tool call: band_send_message with {...}",
                           "2026-10-04 21:45:18,662 INFO x: Complete - 43678ms, $1"])
    head = ("982021e", "Verifier", sent + 1400, "Stage 1 close: HOLDS")
    assert unreported(head, sent, head[2] + UNREPORTED_AFTER - 1, seats) is None  # not quiet long enough
    assert unreported(head, sent, head[2] + UNREPORTED_AFTER + 1, seats) == "verifier"
    assert unreported(head, head[2] + 5, head[2] + 5000, seats) is None  # the room spoke after it
    assert unreported(("abc", "Human", sent + 10, "maint"), sent, sent + 5000, seats) is None


def test_a_seat_mid_turn_means_the_room_is_busy_not_stalled():
    """Regression: the watchdog nudged the planner while the test seat was in a 20-minute
    turn writing a test suite; the quiet room was work, not a lost report."""
    from factory.watchdog import in_turn
    start = "2026-10-04 22:50:01,1 INFO x: Room r: Sending query to Claude SDK (first_msg=False, parts=1)"
    tool = "2026-10-04 22:55:01,1 INFO x: Room r: Tool call: Write with {...}"
    done = "2026-10-04 23:12:05,1 INFO x: Room r: Complete - 1300000ms, $3.1"
    assert in_turn([start, tool], False)
    assert not in_turn([start, tool, done], False)
    assert in_turn([tool], True)  # still the same turn across reads
    no_reply = "2026-10-05 01:58:38,1 INFO x: Room r: no reply this turn (reason: waiting)"
    assert in_turn([start, no_reply, tool], False)  # regression: the builder kept working after it
    assert not in_turn([no_reply, done], True)


def test_a_reconnect_after_a_network_outage_triggers_a_restart():
    """Regression: the host lost DNS three times on 5 Oct; turns running at the time never resumed
    and the band sat idle until someone restarted the seats by hand."""
    from factory.watchdog import network_recovered
    down_line = "2026-10-05 17:50:52 WARNING x: Failed: [Errno -3] Temporary failure in name resolution"
    back_line = "2026-10-05 17:54:10 INFO band.platform.link: WebSocket reconnected — reconciling room state"
    assert network_recovered([down_line], False) == (True, False)
    assert network_recovered([back_line], True) == (False, True)
    assert network_recovered([back_line], False) == (False, False)  # an ordinary reconnect is not an outage
