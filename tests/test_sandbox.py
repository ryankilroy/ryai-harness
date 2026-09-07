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

from ryai_harness.sandbox import Sandbox, SandboxConfig
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
                    "python3 -c \"import socket; "
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
