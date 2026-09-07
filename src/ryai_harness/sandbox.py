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

This module is the interface only (issue #14, TDD stage). Every method
below raises ``NotImplementedError``; the implementation agent fills in
the bodies and owns the Dockerfile / image build. Per ADR 0001 / issue
#11's minimal-dependency policy, the implementation is expected to shell
out to the ``docker`` CLI via ``subprocess`` rather than add a Docker SDK
dependency — that is a strong recommendation from this stage, not a type
this module enforces.

Tool Call contract for this Sandbox: ``name="shell"`` with
``arguments={"command": "<shell string>"}``. The command is run inside
the container via ``/bin/sh -c <command>``. No other tool name is
required by this stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import ClassVar

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import ToolResult


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Configuration for a Sandbox. Every cap here is configuration, not a
    constant baked into ``Sandbox`` — a caller picks the values; nothing in
    this module hardcodes them.

    Attributes:
        image: Docker image tag the container is started from. Defaults to
            ``python:3.12-slim`` — a stock image needing no custom build,
            so this stage's tests are runnable before the implementation
            agent's own Dockerfile exists. Swappable: the implementation
            agent may point this at a project-built image instead.
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

    def __enter__(self) -> Sandbox:
        raise NotImplementedError

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    @property
    def container_id(self) -> str:
        """The running container's id. Valid only between ``__enter__``
        and ``__exit__``."""
        raise NotImplementedError

    def run(self, call: ToolCall) -> ToolResult:
        """Execute one canonical Tool Call inside this Sandbox's
        container and return its canonical Tool Result.

        On success: ``Outcome.OK`` with the command's captured output in
        ``content``. If the wall-clock timeout or memory cap trips: the
        container is killed and the result is ``Outcome.ERROR`` with
        ``content`` naming which cap tripped (the words "timeout" or
        "memory" must appear, case-insensitively — that is the contract
        this stage's tests check).
        """
        raise NotImplementedError
