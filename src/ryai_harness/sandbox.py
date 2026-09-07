"""Local Docker Sandbox — where a side-effecting Tool Call actually runs.

Per ADR 0005 and issue #14: a fresh local Docker container per Slice, torn
down after. The whole repo is bind-mounted read-write in full (no
Blast-Radius-scoped mount), the container process runs as a non-root user,
no Docker socket is mounted, and network access is unrestricted. A
wall-clock timeout and a memory cap bound the container; when either
trips, the Sandbox kills the container itself (a cgroup OOM only kills
the exec'd process, not the container's PID 1 — see the note on
``SandboxConfig.memory_limit`` below) and the tripped call comes back as
a canonical ``error`` Tool Result naming which cap tripped.

Contract for ``timeout_seconds``: it bounds a single ``run()`` call. A
call whose process is still running when its budget elapses is killed,
the container is killed, and that call's Tool Result names the timeout.
This reading is deliberately silent on whether a container also carries a
separate whole-Slice budget (ADR 0005 frames the cap as "per-Slice") —
that is an implementation decision issue #14 does not force, and no test
in this suite depends on which way it goes.

Implementation note (issue #14): the Sandbox shells out to the ``docker``
CLI via ``subprocess`` — no Docker SDK dependency, per ADR 0001 / issue
#11's minimal-dependency policy. No project-built image was needed: stock
``python:3.12-slim`` plus ``docker run --user <uid>:<uid>`` already
satisfies the non-root AC, verified against real Docker, and a
locally-built-only default image tag would break the test suite's own
``docker pull`` of ``SandboxConfig().image`` (there would be nothing on
a registry to pull). ``SandboxConfig.image`` stays configuration so a
project-built image remains a drop-in swap later if isolation needs ever
outgrow this.

Tool Call contract for this Sandbox: ``name="shell"`` with
``arguments={"command": "<shell string>"}``. The command is run inside
the container via ``/bin/sh -c <command>``. No other tool name is
required by this stage.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Final

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult

# Non-root uid/gid the container runs as, passed via `docker run --user`.
# Not baked into a custom image or resolved against /etc/passwd inside the
# container -- Docker accepts an arbitrary numeric uid, and the tests only
# require "not root" (uid 0), never a specific name or shell entry.
_NONROOT_UID: Final = 1000

# Timeout for this module's own `docker` CLI admin calls (run/kill/rm/
# inspect) -- independent of `SandboxConfig.timeout_seconds`, which bounds
# only the `docker exec` that runs a Tool Call's command. Generous because
# these are lifecycle operations, not the thing under test.
_DOCKER_ADMIN_TIMEOUT_SECONDS: Final = 30.0


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Configuration for a Sandbox. Every cap here is configuration, not a
    constant baked into ``Sandbox`` — a caller picks the values; nothing in
    this module hardcodes them.

    Attributes:
        image: Docker image tag the container is started from. Defaults to
            ``python:3.12-slim`` — a stock image, deliberately not a
            project-built one: combined with ``docker run --user``, it
            already satisfies every AC this stage tests (non-root, no
            Docker socket, fresh per Slice), so a custom Dockerfile would
            add a build step this ticket doesn't need. Still swappable —
            a project-built image is a drop-in ``SandboxConfig.image``
            change if isolation needs ever outgrow this.
        repo_path: Host path bind-mounted read-write, in full, into the
            container at ``mount_path``.
        mount_path: Path inside the container where ``repo_path`` is
            mounted.
        timeout_seconds: Wall-clock budget for a single ``run()`` call.
            See the module docstring's "Contract for timeout_seconds".
            Generous placeholder; tuned later from observed behaviour per
            ADR 0005 — not a blocking decision for this ticket.
        memory_limit: Docker ``--memory``-style limit string (e.g.
            ``"256m"``, ``"1g"``) applied to the container. Generous
            placeholder, same status as ``timeout_seconds``. Note: a
            cgroup OOM triggered by a single ``run()`` call kills that
            call's process, not necessarily the container's PID 1 — the
            Sandbox is responsible for detecting the OOM and killing the
            container itself so the cap's trip is observable from
            outside (AC: "the container is killed").
    """

    image: str = "python:3.12-slim"
    repo_path: Path = Path(".")
    mount_path: str = "/workspace"
    timeout_seconds: float = 30.0
    memory_limit: str = "256m"


class Sandbox:
    """A fresh local Docker container, one per Slice.

    Usage is a context manager: entering starts the container, exiting
    tears it down (stops and removes it) unconditionally — no container
    outlives the ``with`` block. ``run()`` executes one canonical
    ``ToolCall`` inside the running container (via ``docker exec``, in the
    expected implementation) and returns a canonical ``ToolResult``.

    Every container this class creates must carry the ``CONTAINER_LABEL``
    label (as a Docker ``--label`` argument, verbatim). Tests use this
    label to find and assert against this Sandbox's own containers, and to
    sweep for containers that were never torn down.
    """

    CONTAINER_LABEL: ClassVar[str] = "ryai-harness-sandbox=1"

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._container_id: str | None = None

    def __enter__(self) -> Sandbox:
        cfg = self._config
        host_path = str(cfg.repo_path.resolve())
        args = [
            "docker",
            "run",
            "-d",
            "--label",
            self.CONTAINER_LABEL,
            "--user",
            f"{_NONROOT_UID}:{_NONROOT_UID}",
            "--memory",
            cfg.memory_limit,
            # Equal to --memory: disables swap for the container, so a
            # cap trip is a real OOM kill, not silently absorbed by swap.
            "--memory-swap",
            cfg.memory_limit,
            "-v",
            f"{host_path}:{cfg.mount_path}",
            "-w",
            cfg.mount_path,
            cfg.image,
            "sleep",
            "infinity",
        ]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_DOCKER_ADMIN_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to start sandbox container: {result.stderr.strip()}")
        # Assign only after the container is confirmed started, and do
        # nothing else that could raise below -- once `_container_id` is
        # set, `__exit__` is the only thing responsible for tearing the
        # container down, and it only runs if `__enter__` returns.
        self._container_id = result.stdout.strip()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Unconditional teardown: stop-and-remove regardless of whether a
        # trip already killed the container, and never let a docker-CLI
        # hiccup here raise out of __exit__ and mask an in-flight
        # exception (or, with none in flight, escape as its own).
        if self._container_id is not None:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_id],
                    capture_output=True,
                    text=True,
                    timeout=_DOCKER_ADMIN_TIMEOUT_SECONDS,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            self._container_id = None

    @property
    def container_id(self) -> str:
        """The running container's id. Valid only between ``__enter__``
        and ``__exit__``."""
        if self._container_id is None:
            raise RuntimeError("Sandbox.container_id is only valid between __enter__ and __exit__")
        return self._container_id

    def run(self, call: ToolCall) -> ToolResult:
        """Execute one canonical Tool Call inside this Sandbox's
        container and return its canonical Tool Result.

        On success: ``Outcome.OK`` with the command's captured output in
        ``content``. If the wall-clock timeout or memory cap trips: the
        container is killed and the result is ``Outcome.ERROR`` with
        ``content`` naming which cap tripped (the words "timeout" or
        "memory" must appear, case-insensitively — that is the contract
        this stage's tests check).

        A command that runs to completion but exits non-zero for a reason
        other than a cap trip is still ``Outcome.OK``: the Tool Call
        itself executed inside the container and produced a result.
        ``Outcome.ERROR`` in this Sandbox is reserved for the two cap
        trips this stage owns — ADR 0002 draws this line explicitly (a
        no-match search is ``ok`` with empty content; a nonzero shell
        exit is the same shape of "ran fine, reported nothing/failure").
        What must not happen is losing the exit status along the way:
        ``content`` carries an extra ``"exit status: <n>"`` element
        whenever ``proc.returncode != 0``, appended only in that case so
        every exit-0 command's ``content`` (what every test in this
        stage's suite exercises) is unchanged. Without this, nothing
        downstream — a future Test Gate shelling out to ``pytest``,
        for instance — could tell a passing run from a failing one from
        the Tool Result alone.
        """
        cid = self.container_id
        command = call.arguments["command"]
        if not isinstance(command, str):
            raise TypeError(
                f'Sandbox.run requires arguments["command"] to be a str, got {command!r}'
            )

        timeout_seconds = self._config.timeout_seconds
        try:
            proc = subprocess.run(
                ["docker", "exec", cid, "/bin/sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            self._kill_container(cid)
            return ToolResult(
                outcome=Outcome.ERROR,
                content=(f"tool call exceeded the sandbox timeout of {timeout_seconds}s",),
            )

        if proc.returncode != 0 and self._container_oom_killed(cid):
            self._kill_container(cid)
            return ToolResult(
                outcome=Outcome.ERROR,
                content=(
                    f"tool call exceeded the sandbox memory cap ({self._config.memory_limit})",
                ),
            )

        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            return ToolResult(
                outcome=Outcome.OK,
                content=(output, f"exit status: {proc.returncode}"),
            )
        return ToolResult(outcome=Outcome.OK, content=(output,))

    def _kill_container(self, container_id: str) -> None:
        # Best-effort: the trip that got us here may have already left
        # the container in a state where `docker kill` errors (e.g.
        # already dead) -- __exit__ still does the unconditional
        # stop-and-remove, so nothing here needs to be fatal.
        try:
            subprocess.run(
                ["docker", "kill", container_id],
                capture_output=True,
                text=True,
                timeout=_DOCKER_ADMIN_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _container_oom_killed(self, container_id: str) -> bool:
        # KNOWN BUG (issue #25), reproduced in
        # tests/test_sandbox.py::TestMultipleRunsOnOneSandbox: this reads
        # a container-wide latch that never clears for the container's
        # life. A memory-cap trip on one `run()` call whose exit is
        # swallowed (e.g. `... || true`) leaves this reading `true`
        # forever after, so a later, wholly unrelated non-zero exit on
        # the same container gets misattributed as a memory-cap trip.
        #
        # Handoff facts verified against real Docker (29.4.1, cgroup v2)
        # while diagnosing this:
        #   - `docker exec <cid> cat /sys/fs/cgroup/memory.events` is
        #     readable as the container's non-root user (uid 1000) and
        #     exposes an `oom_kill <n>` field that is a monotonic
        #     per-container counter, not a sticky bool: it goes
        #     1 -> 1 (an unrelated non-zero exit does not bump it)
        #     -> 2 (a second, genuine OOM does).
        #   - A fix must diff this counter against a baseline captured
        #     before the specific `run()` call being judged -- a bool
        #     snapshotted once (e.g. at `__enter__`) cannot distinguish
        #     "still the old trip" from "a second new trip" once it has
        #     already latched true, so it cannot satisfy the AC that a
        #     later genuine trip is still detected.
        #   - cgroup v1 hosts would need a different signal (e.g.
        #     `memory.failcnt`) -- not verified here.
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.OOMKilled}}", container_id],
            capture_output=True,
            text=True,
            timeout=_DOCKER_ADMIN_TIMEOUT_SECONDS,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
