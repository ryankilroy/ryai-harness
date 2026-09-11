"""Tests for the local Docker Sandbox (issue #14, ADR 0005).

External behaviour only: given a canonical Tool Call executed inside a
Sandbox, expect a canonical Tool Result and container lifecycle
observable from outside via the Docker CLI. Nothing here mocks Docker —
every test that touches it runs a real local container, per this
ticket's explicit AC — and every direct `docker` CLI call this file makes
itself carries a hard timeout (`_docker`'s `timeout` argument) so a hang
here cannot stall the suite. Today, before the implementation exists,
every behavioural test below fails fast on `NotImplementedError` from
`Sandbox.__enter__` before touching Docker at all — there is nothing to
hang on yet. Once implemented, the small placeholder caps used below
(seconds, not minutes; tens of MB, not GB) keep the suite fast.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from ryai_harness.sandbox import OomStatus, Sandbox, SandboxConfig
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult

# Small placeholder caps -- generous enough for a `python3 -c` one-liner
# to finish comfortably, tight enough that trip tests resolve in seconds.
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MEMORY_LIMIT = "128m"

# Hard ceiling on any `docker` CLI call this test file makes directly
# (lifecycle assertions, cleanup, the leak sweep) -- independent of
# whatever timeout Sandbox enforces internally.
DOCKER_CLI_TIMEOUT = 15


def _docker(*args: str, timeout: int = DOCKER_CLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a `docker` CLI command with a hard timeout. Never mocked."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _shell_call(command: str, call_id: str = "c1") -> ToolCall:
    """A canonical Tool Call whose sole argument is a shell command
    string, run inside the Sandbox's container via `/bin/sh -c`. See
    sandbox.py's module docstring for this stage's Tool Call contract."""
    return ToolCall(call_id=call_id, name="shell", arguments={"command": command})


def _output(result: ToolResult) -> str:
    return "".join(result.content)


@pytest.fixture(scope="session", autouse=True)
def _pull_sandbox_image() -> None:
    # Pre-pull so a cold image pull can never be what makes __enter__
    # look slow or hung once it's implemented. Generous timeout here
    # only, since a real pull (unlike everything else in this file) can
    # legitimately take a while on a fresh machine.
    _docker("pull", SandboxConfig().image, timeout=120)


@pytest.fixture(scope="module", autouse=True)
def _no_sandbox_containers_survive_the_module() -> Iterator[None]:
    """Module-scoped safety net for the headline AC: after every test in
    this module has run, zero containers carrying Sandbox's label may
    remain, labeled or not torn down. A single leaked container (a buggy
    `close()`/`__exit__`) fails this, independent of what any individual
    test already checked. Note for whoever reads pipeline output: a
    failure here surfaces as a pytest ERROR on teardown of the last test
    in this module, not as a named FAILED test -- that's a module-level
    leak, not a collection error."""
    yield

    leaked = _docker("ps", "-aq", "--filter", f"label={Sandbox.CONTAINER_LABEL}")
    assert leaked.returncode == 0
    leaked_ids = leaked.stdout.split()
    if leaked_ids:
        _docker("rm", "-f", *leaked_ids)  # clean up before failing
    assert leaked_ids == [], f"sandbox containers outlived their Slice: {leaked_ids}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo directory standing in for the real one. Tests
    must never bind-mount the actual working tree they run from."""
    (tmp_path / "marker.txt").write_text("host-authored\n")
    return tmp_path


@pytest.fixture
def sandbox_config(repo: Path) -> SandboxConfig:
    return SandboxConfig(
        repo_path=repo,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        memory_limit=DEFAULT_MEMORY_LIMIT,
    )


class TestContainerLifecycle:
    def test_container_is_labeled_and_running_while_sandbox_is_open(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            found = _docker(
                "ps",
                "-q",
                "--filter",
                f"id={sb.container_id}",
                "--filter",
                f"label={Sandbox.CONTAINER_LABEL}",
            )
            assert found.stdout.strip() != "", "container missing, not running, or unlabeled"

    def test_container_is_torn_down_after_sandbox_closes(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            container_id = sb.container_id

        # Torn down means gone, not merely stopped: inspect must fail
        # once the `with` block has exited.
        inspected = _docker("inspect", container_id)
        assert inspected.returncode != 0

    def test_a_new_sandbox_does_not_see_state_from_a_previous_one(
        self, sandbox_config: SandboxConfig
    ) -> None:
        # Container-local path, deliberately *not* under mount_path --
        # this only passes if containers are genuinely fresh, not because
        # the bind mount happens to be empty.
        with Sandbox(sandbox_config) as first:
            write_result = first.run(_shell_call("echo leftover > /tmp/marker && cat /tmp/marker"))
            # The write must actually have happened -- otherwise "absent"
            # in the second sandbox would prove nothing about freshness.
            assert write_result.outcome is Outcome.OK
            assert "leftover" in _output(write_result)

        with Sandbox(sandbox_config) as second:
            result = second.run(_shell_call("test -f /tmp/marker && echo found || echo absent"))

        assert result.outcome is Outcome.OK
        assert _output(result).strip() == "absent"


class TestBindMount:
    def test_write_from_inside_container_visible_on_host(
        self, sandbox_config: SandboxConfig, repo: Path
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            result = sb.run(
                _shell_call(
                    f"echo container-wrote-this > {sandbox_config.mount_path}/from_container.txt"
                )
            )
            assert result.outcome is Outcome.OK

        written = repo / "from_container.txt"
        assert written.exists()
        assert written.read_text().strip() == "container-wrote-this"

    def test_host_authored_file_is_readable_from_inside(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            result = sb.run(_shell_call(f"cat {sandbox_config.mount_path}/marker.txt"))

        assert result.outcome is Outcome.OK
        assert "host-authored" in _output(result)


class TestNonRootUser:
    def test_process_does_not_run_as_root(self, sandbox_config: SandboxConfig) -> None:
        with Sandbox(sandbox_config) as sb:
            result = sb.run(_shell_call("id -u"))

        assert result.outcome is Outcome.OK
        uid = _output(result).strip()
        assert uid.isdigit()
        assert uid != "0"


class TestNoDockerSocket:
    def test_docker_socket_is_not_reachable_from_inside(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            result = sb.run(
                _shell_call("test -S /var/run/docker.sock && echo present || echo absent")
            )

        assert result.outcome is Outcome.OK
        assert _output(result).strip() == "absent"


class TestNetworkAccess:
    def test_outbound_network_is_reachable(self, sandbox_config: SandboxConfig) -> None:
        with Sandbox(sandbox_config) as sb:
            result = sb.run(
                _shell_call(
                    'python3 -c "import socket; '
                    "socket.create_connection(('8.8.8.8', 53), timeout=5); "
                    "print('reachable')\""
                )
            )

        assert result.outcome is Outcome.OK
        assert "reachable" in _output(result)


class TestWallClockTimeout:
    def test_exceeding_the_timeout_kills_the_container_and_names_it(self, repo: Path) -> None:
        config = SandboxConfig(
            repo_path=repo, timeout_seconds=1.0, memory_limit=DEFAULT_MEMORY_LIMIT
        )

        with Sandbox(config) as sb:
            container_id = sb.container_id
            result = sb.run(_shell_call("sleep 30"))
            # Checked *inside* the `with` block, before __exit__ runs its
            # own teardown -- this proves the trip itself killed the
            # container, not the later, unconditional close.
            state = _docker("inspect", "-f", "{{.State.Running}}", container_id)

        assert result.outcome is Outcome.ERROR
        assert "timeout" in _output(result).lower()
        assert state.returncode != 0 or state.stdout.strip() != "true"


class TestMemoryCap:
    def test_exceeding_the_memory_cap_kills_the_container_and_names_it(self, repo: Path) -> None:
        # A cgroup OOM from a single exec'd process does not by itself
        # kill the container's PID 1 (confirmed against real Docker while
        # designing this test) -- the Sandbox must detect the OOM and
        # kill the container itself. 64m keeps CPython's own startup RSS
        # well clear of the cap; 512MB of allocation trips it hard.
        config = SandboxConfig(
            repo_path=repo, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, memory_limit="64m"
        )

        with Sandbox(config) as sb:
            container_id = sb.container_id
            result = sb.run(_shell_call('python3 -c "bytearray(512 * 1024 * 1024)"'))
            state = _docker("inspect", "-f", "{{.State.Running}}", container_id)

        assert result.outcome is Outcome.ERROR
        assert "memory" in _output(result).lower()
        assert state.returncode != 0 or state.stdout.strip() != "true"


class TestMultipleRunsOnOneSandbox:
    """Issue #25: `State.OOMKilled` latches true for the life of the
    container and never clears -- verified against real Docker (Docker
    29.4.1 / cgroup v2): a call whose OOM is swallowed by `|| true` exits
    0, leaving `State.OOMKilled=true` and `State.Running=true`, and that
    `true` is still read back after a later, wholly unrelated non-zero
    exit on the same container. `Sandbox.run`'s only guard today is
    ``proc.returncode != 0`` combined with that latched field, so the
    later call is misreported as a memory-cap trip and its container is
    killed for a benign failure.

    Every test in the rest of this module makes exactly one `run()` call
    per Sandbox, so this file-wide behaviour was untested before this
    class. Both tests below share the same first call -- an OOM whose
    exit is swallowed by `|| true`, so the call itself reports `ok` and
    the container survives to take a second `run()`.
    """

    def test_earlier_swallowed_oom_does_not_misattribute_a_later_benign_failure(
        self, repo: Path
    ) -> None:
        config = SandboxConfig(
            repo_path=repo, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, memory_limit="64m"
        )

        with Sandbox(config) as sb:
            container_id = sb.container_id

            oom_result = sb.run(
                _shell_call('python3 -c "bytearray(512 * 1024 * 1024)" || true', call_id="c1")
            )
            # Sanity on the setup, not the bug: `|| true` must actually
            # swallow the OOM's exit so this call reports ok and the
            # container is still alive to take a second call. If this
            # fails, the rest of the test proves nothing about the latch.
            assert oom_result.outcome is Outcome.OK, (
                "setup invariant broken: the OOM's exit was not swallowed by `|| true`"
            )

            benign_result = sb.run(_shell_call("exit 3", call_id="c2"))
            state = _docker("inspect", "-f", "{{.State.Running}}", container_id)

        # This is the latch: call 2 is an ordinary `exit 3` with no
        # memory involved. A Sandbox that correctly scopes its
        # memory-cap attribution to the run it is judging reports this
        # as `ok` (a non-zero exit is not a cap trip -- ADR 0002 / #14).
        # Today it reports `error` naming memory, because
        # `_container_oom_killed` reads the container-wide latch left
        # over from call 1 instead of anything scoped to call 2.
        assert benign_result.outcome is Outcome.OK, (
            "call 2 (`exit 3`, no memory involved) was misreported as a memory-cap trip -- "
            f"this is the State.OOMKilled latch from call 1's OOM leaking into call 2's "
            f"verdict: {benign_result!r}"
        )
        assert _output(benign_result) == "exit status: 3"
        # AC: "a container killed for a real cap trip is still torn
        # down; one that merely returned a non-zero exit is not" -- a
        # benign `exit 3` must leave the container running.
        assert state.returncode == 0 and state.stdout.strip() == "true", (
            "container was killed for call 2's benign `exit 3`, not a real cap trip"
        )

    def test_later_genuine_oom_is_still_detected_after_an_earlier_swallowed_oom(
        self, repo: Path
    ) -> None:
        # This is a guard, not a reproduction of the bug: it passes
        # today, but for the wrong reason -- the latch left over from
        # call 1 already reads true, so call 2's *real* OOM is "detected"
        # by coincidence, not because it was observed. A latched boolean
        # cannot distinguish "still the old trip" from "a second, new
        # trip" -- verified directly: `memory.events`' `oom_kill` counter
        # goes 1 -> 1 (unrelated exit) -> 2 (a second real OOM), so only
        # a per-call counter diff satisfies both this test and the one
        # above at once. A fix that merely snapshots the boolean latch at
        # `__enter__` and treats a transition as a trip would pass the
        # test above but fail this one on the container's *second* real
        # OOM, since a bool has nowhere left to transition to.
        config = SandboxConfig(
            repo_path=repo, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, memory_limit="64m"
        )

        with Sandbox(config) as sb:
            container_id = sb.container_id

            first = sb.run(
                _shell_call('python3 -c "bytearray(512 * 1024 * 1024)" || true', call_id="c1")
            )
            assert first.outcome is Outcome.OK

            second = sb.run(_shell_call('python3 -c "bytearray(512 * 1024 * 1024)"', call_id="c2"))
            state = _docker("inspect", "-f", "{{.State.Running}}", container_id)

        assert second.outcome is Outcome.ERROR
        assert "memory" in _output(second).lower()
        assert state.returncode != 0 or state.stdout.strip() != "true"


class TestCapsAreConfiguration:
    def test_timeout_is_a_config_field_not_a_constant(self, repo: Path) -> None:
        generous = SandboxConfig(
            repo_path=repo, timeout_seconds=30.0, memory_limit=DEFAULT_MEMORY_LIMIT
        )
        with Sandbox(generous) as sb:
            result = sb.run(_shell_call("sleep 2"))
        assert result.outcome is Outcome.OK

        # Same command shape, only the config changed -- the trip is a
        # function of configuration, not a value baked into Sandbox.
        strict = SandboxConfig(
            repo_path=repo, timeout_seconds=1.0, memory_limit=DEFAULT_MEMORY_LIMIT
        )
        with Sandbox(strict) as sb:
            result = sb.run(_shell_call("sleep 5"))
        assert result.outcome is Outcome.ERROR
        assert "timeout" in _output(result).lower()

    def test_memory_cap_is_a_config_field_not_a_constant(self, repo: Path) -> None:
        generous = SandboxConfig(
            repo_path=repo, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, memory_limit="512m"
        )
        with Sandbox(generous) as sb:
            result = sb.run(_shell_call('python3 -c "bytearray(50 * 1024 * 1024)"'))
        assert result.outcome is Outcome.OK

        strict = SandboxConfig(
            repo_path=repo, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, memory_limit="64m"
        )
        with Sandbox(strict) as sb:
            result = sb.run(_shell_call('python3 -c "bytearray(512 * 1024 * 1024)"'))
        assert result.outcome is Outcome.ERROR
        assert "memory" in _output(result).lower()


class TestUndeterminableOomCountDoesNotTrip:
    """A memory-cap trip is claimed only on positive evidence.

    ``_oom_kill_count`` returns ``None``, never ``0``, when the counter
    cannot be read -- an unreadable cgroup file, a cgroup v1 host, a
    docker-CLI hiccup. Both readings feed a strict ``after > before``
    comparison, so neither may be silently treated as a number.

    Issue #27 replaces the old boolean fold (an undeterminable reading
    used to collapse to ``False``, indistinguishable from a confirmed
    non-trip) with a tri-state ``OomStatus``: ``OOM_KILLED``,
    ``NOT_OOM_KILLED``, ``UNDETERMINED``. These tests pin that either
    reading being unreadable yields ``UNDETERMINED``, never silently
    folded into either of the other two -- before the original pair of
    tests existed, flipping both branches to report a trip left the
    whole suite passing, so the polarity was unpinned in either
    direction; this generalises that guard to three states instead of
    two.

    Deliberate deviation from this module's "external behaviour only"
    rule, and the first of two such deviations in this file (see
    ``TestUndeterminedOomStatusSurfacesFromRun`` below for the second):
    reaching these branches from outside needs a cgroup v1 host or a
    failing docker CLI, neither of which the suite can produce. The
    alternative was to leave the policy untested, which is worse -- but
    the coupling to two private names is real, and if either is renamed
    these tests break for a reason that has nothing to do with the
    behaviour they guard.
    """

    def test_an_unreadable_baseline_reads_as_undetermined(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            # `None` is exactly what run() would hold had its own baseline
            # read failed; the after-reading here is a real, readable count.
            assert sb._oom_status(sb.container_id, None) is OomStatus.UNDETERMINED

    def test_an_unreadable_after_count_reads_as_undetermined(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            # A container id that cannot be exec'd into makes the *after*
            # read fail while the baseline is a perfectly good integer --
            # the mirror of the case above.
            assert sb._oom_status("ryai-harness-no-such-container", 0) is OomStatus.UNDETERMINED

    def test_an_unreadable_counter_reads_as_unknown_not_as_zero(
        self, sandbox_config: SandboxConfig
    ) -> None:
        # The distinction the two tests above rest on. Were this `0`, a
        # failed baseline read followed by a good reading at a leftover
        # non-zero count would report a trip that never happened -- #25's
        # misattribution, one level down.
        with Sandbox(sandbox_config) as sb:
            assert sb._oom_kill_count("ryai-harness-no-such-container") is None


class TestUndeterminedOomStatusSurfacesFromRun:
    """Issue #27: an ``UNDETERMINED`` OOM-cap reading must reach
    ``run()``'s caller as a distinct, visible value -- never silently
    folded into the same shape as a confirmed non-trip. That collapse is
    exactly the bug #27 reports: "couldn't tell" had nowhere to go, so it
    read as a confident "no trip".

    Second deliberate deviation from this file's "nothing mocks Docker"
    rule (the first is ``TestUndeterminableOomCountDoesNotTrip`` above):
    the only way to make a real container's OOM-counter reads
    unreadable, from outside, is a cgroup v1 host or a failing docker
    CLI, neither reachable from this suite. ``monkeypatch`` forces
    ``_oom_kill_count`` to return ``None`` the way either real cause
    would, while the container underneath keeps running for real and the
    command it runs actually executes and exits non-zero.
    """

    def test_undetermined_status_is_distinguishable_from_a_plain_failure(
        self, sandbox_config: SandboxConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            plain_failure = sb.run(_shell_call("exit 7"))

            monkeypatch.setattr(sb, "_oom_kill_count", lambda container_id: None)
            undetermined = sb.run(_shell_call("exit 7"))

        assert plain_failure.outcome is Outcome.OK
        assert "exit status: 7" in _output(plain_failure)
        assert "undetermined" not in _output(plain_failure).lower()

        assert undetermined.outcome is Outcome.OK
        assert "exit status: 7" in _output(undetermined)
        assert "undetermined" in _output(undetermined).lower()
