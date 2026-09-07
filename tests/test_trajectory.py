"""Tests for the Trajectory writer + diff capture (issue #16, ADR 0001,
ADR 0003, ADR 0007).

External behaviour only, in the same style as tests/test_tool_result.py
and tests/test_sandbox.py: given a construction or a call, expect this
value, this failure, or this observable side effect. Schema tests
(``TestTrajectorySchema`` and friends) construct ``Trajectory`` directly
and are expected to pass even before ``capture_diff``/``write_trajectory``
are implemented — the dataclass itself has no stub body. Every test that
calls ``capture_diff`` or ``write_trajectory`` is expected to fail on
``NotImplementedError`` until the implement stage fills those bodies in;
that is this stage's intended "red."

Two tests touch real Docker (``TestCaptureDiffFromSandboxBindMount`` and
``TestSandboxCapTripSurfacesAsFailedTrajectory``), per this ticket's
brief: never mock Docker, one ``run()`` per ``Sandbox`` (issue #14's
review found that ``Sandbox._container_oom_killed`` reads Docker's
``State.OOMKilled``, which latches true and never clears — a second
``run()`` on the same Sandbox after an earlier trip is misreported), and
every direct ``docker`` CLI call this file makes carries a hard timeout
so a hung container cannot stall the suite.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

import ryai_harness.trajectory
from ryai_harness.sandbox import Sandbox, SandboxConfig
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult
from ryai_harness.trajectory import (
    GateVerdict,
    TerminationReason,
    Trajectory,
    capture_diff,
    write_trajectory,
)

# Hard ceiling on any `docker`/`git` CLI call this file makes directly.
_CLI_TIMEOUT = 15


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT,
        check=True,
    )


def _docker(*args: str, timeout: int = _CLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="session", autouse=True)
def _pull_sandbox_image() -> None:
    # Pre-pull once for the whole session so a cold pull can never
    # masquerade as a hang in Sandbox.__enter__'s own 30s admin timeout
    # -- same rationale as test_sandbox.py's fixture of the same name.
    # Harmless (and fast, already-cached) if test_sandbox.py's own
    # session-scoped fixture already pulled it first.
    _docker("pull", SandboxConfig().image, timeout=120)


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway git repo standing in for the Sandbox's bind-mounted
    checkout, with one tracked file committed. Returns (repo_path,
    base_commit) -- the commit a Slice attempt would have started from."""
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "trajectory-tests@example.invalid")
    _git(repo, "config", "user.name", "Trajectory Tests")
    (repo / "tracked.txt").write_text("original\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    base_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, base_commit


def _full_trajectory(
    *,
    diff: str = "",
    gate_verdict: GateVerdict = GateVerdict.PASS,
    gate_command_result: ToolResult | None = None,
    termination_reason: TerminationReason = TerminationReason.MODEL_FINISHED,
) -> Trajectory:
    """A fully-populated Trajectory for tests that don't care about every
    field's exact value -- only that a real value is present at all."""
    if gate_command_result is None:
        gate_command_result = ToolResult(outcome=Outcome.OK, content=("36 passed",))
    return Trajectory(
        tool_calls=(ToolCall(call_id="c1", name="shell", arguments={"command": "echo hi"}),),
        tool_results=(ToolResult(outcome=Outcome.OK, content=("hi",)),),
        diff=diff,
        gate_command_result=gate_command_result,
        gate_verdict=gate_verdict,
        termination_reason=termination_reason,
        cost=0.0123,
        duration_seconds=42.5,
    )


class TestTrajectorySchema:
    """AC 1, AC 2: every field present, on every path -- success, a
    failing gate, and a Slice that errored before completion."""

    def test_every_field_present_for_a_successful_slice(self) -> None:
        traj = Trajectory(
            tool_calls=(ToolCall(call_id="c1", name="shell", arguments={"command": "echo hi"}),),
            tool_results=(ToolResult(outcome=Outcome.OK, content=("hi",)),),
            diff="diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
            gate_command_result=ToolResult(outcome=Outcome.OK, content=("36 passed",)),
            gate_verdict=GateVerdict.PASS,
            termination_reason=TerminationReason.MODEL_FINISHED,
            cost=0.0123,
            duration_seconds=42.5,
        )

        assert traj.tool_calls[0].name == "shell"
        assert traj.tool_results[0].outcome is Outcome.OK
        assert traj.diff.startswith("diff --git")
        assert traj.gate_command_result.outcome is Outcome.OK
        assert traj.gate_verdict is GateVerdict.PASS
        assert traj.termination_reason is TerminationReason.MODEL_FINISHED
        assert traj.cost == 0.0123
        assert traj.duration_seconds == 42.5

    def test_every_field_present_for_a_failing_slice(self) -> None:
        # The gate ran and failed -- not silently dropped, not a partial
        # record; every field is a real value, same as the passing case.
        traj = Trajectory(
            tool_calls=(ToolCall(call_id="c1", name="shell", arguments={"command": "pytest"}),),
            tool_results=(ToolResult(outcome=Outcome.OK, content=("2 failed",)),),
            diff="diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+broken\n",
            gate_command_result=ToolResult(outcome=Outcome.OK, content=("2 failed, 34 passed",)),
            gate_verdict=GateVerdict.FAIL,
            termination_reason=TerminationReason.MODEL_FINISHED,
            cost=0.09,
            duration_seconds=17.0,
        )

        assert traj.gate_verdict is GateVerdict.FAIL
        assert traj.gate_command_result.content == ("2 failed, 34 passed",)
        assert traj.diff != ""

    def test_every_field_present_for_a_slice_that_errored_before_completion(self) -> None:
        # AC 2: no partial or missing record on a failure path. The gate
        # command never ran -- per this module's documented convention,
        # that is still a real, non-omitted ToolResult (Outcome.ERROR
        # naming that the gate did not run), paired with FAIL and the
        # HARNESS_ERROR termination reason (see trajectory.py's module
        # docstring for why that reason has its own member).
        traj = Trajectory(
            tool_calls=(),
            tool_results=(
                ToolResult(outcome=Outcome.ERROR, content=("harness crashed: OSError",)),
            ),
            diff="",
            gate_command_result=ToolResult(
                outcome=Outcome.ERROR,
                content=("gate did not run: Slice attempt errored before completion",),
            ),
            gate_verdict=GateVerdict.FAIL,
            termination_reason=TerminationReason.HARNESS_ERROR,
            cost=0.004,
            duration_seconds=3.1,
        )

        assert traj.tool_calls == ()
        assert traj.termination_reason is TerminationReason.HARNESS_ERROR
        assert traj.gate_verdict is GateVerdict.FAIL
        assert traj.gate_command_result.outcome is Outcome.ERROR
        assert "did not run" in "".join(traj.gate_command_result.content)

    def test_empty_tool_calls_and_tool_results_are_present_not_absent(self) -> None:
        # A Slice that errored before issuing a single Tool Call still
        # has tool_calls=() -- a real, present empty tuple -- not a
        # missing field.
        traj = _full_trajectory()
        empty = dataclasses.replace(traj, tool_calls=(), tool_results=())

        assert empty.tool_calls == ()
        assert empty.tool_results == ()

    def test_all_fields_are_required_no_defaults(self) -> None:
        # Nothing that assembles a Trajectory can omit a field by
        # accident -- same discipline as ToolResult.outcome (issue #11).
        for f in dataclasses.fields(Trajectory):
            assert f.default is dataclasses.MISSING, f"{f.name} has a default"
            assert (
                f.default_factory is dataclasses.MISSING  # type: ignore[comparison-overlap]
            ), f"{f.name} has a default_factory"

    def test_missing_field_fails_loudly_at_construction(self) -> None:
        with pytest.raises(TypeError):
            Trajectory(  # type: ignore[call-arg]
                tool_calls=(),
                tool_results=(),
                diff="",
            )

    def test_trajectory_is_immutable(self) -> None:
        traj = _full_trajectory()
        with pytest.raises(dataclasses.FrozenInstanceError):
            traj.diff = "changed"  # type: ignore[misc]


class TestDiffFieldNeverOptional:
    """AC 5's structural half: an empty diff and an absent diff can never
    be confused, because the field's own type admits no absent value.
    Same pattern as tests/test_tool_result.py's
    test_content_field_type_never_admits_none -- relies on trajectory.py
    keeping `from __future__ import annotations`."""

    def test_diff_field_type_never_admits_none(self) -> None:
        diff_field = next(f for f in dataclasses.fields(Trajectory) if f.name == "diff")

        assert "None" not in diff_field.type
        assert "Optional" not in diff_field.type

    def test_gate_command_result_field_type_never_admits_none(self) -> None:
        f = next(f for f in dataclasses.fields(Trajectory) if f.name == "gate_command_result")

        assert "None" not in f.type
        assert "Optional" not in f.type

    def test_empty_diff_is_a_valid_distinct_value(self) -> None:
        made_no_changes = _full_trajectory(diff="")

        assert made_no_changes.diff == ""
        assert made_no_changes.diff is not None


class TestTerminationReasonEnum:
    """AC 7: distinct values for a model-initiated finish and each stop
    condition, no default, never inferred by absence."""

    def test_has_five_distinct_members(self) -> None:
        assert len(TerminationReason) == 5
        assert len({m.value for m in TerminationReason}) == 5

    def test_model_finished_and_every_stop_condition_are_distinct(self) -> None:
        stop_conditions = {
            TerminationReason.ITERATION_CAP,
            TerminationReason.COST_CAP,
            TerminationReason.WALL_CLOCK_CAP,
        }

        assert TerminationReason.MODEL_FINISHED not in stop_conditions
        assert len(stop_conditions) == 3

    def test_harness_error_is_distinct_from_the_other_four(self) -> None:
        the_other_four = {
            TerminationReason.MODEL_FINISHED,
            TerminationReason.ITERATION_CAP,
            TerminationReason.COST_CAP,
            TerminationReason.WALL_CLOCK_CAP,
        }

        assert TerminationReason.HARNESS_ERROR not in the_other_four

    def test_termination_reason_field_has_no_default(self) -> None:
        f = next(f for f in dataclasses.fields(Trajectory) if f.name == "termination_reason")

        assert f.default is dataclasses.MISSING


class TestGateVerdictEnum:
    def test_has_exactly_two_members_pass_and_fail(self) -> None:
        assert {m.value for m in GateVerdict} == {"pass", "fail"}
        assert len(GateVerdict) == 2

    def test_gate_verdict_field_has_no_default(self) -> None:
        f = next(f for f in dataclasses.fields(Trajectory) if f.name == "gate_verdict")

        assert f.default is dataclasses.MISSING


class TestWriterNeverTransmits:
    """AC 3: nothing in the writer transmits a Trajectory anywhere.
    Checked structurally against this module's own imports (AST, not
    regex, so this module's own prose about sockets/networks in its
    docstrings can't false-positive the scan) -- scoped to trajectory.py
    only, not the whole package: ADR 0001 has the Harness reach a Model
    Backend over HTTP, so a package-wide ban would break once that
    client lands (issues #17-#19)."""

    _FORBIDDEN_MODULES = frozenset(
        {"socket", "urllib", "http", "ftplib", "smtplib", "requests", "httpx", "aiohttp"}
    )

    def test_trajectory_module_imports_nothing_networked(self) -> None:
        module_path = Path(ryai_harness.trajectory.__file__)
        tree = ast.parse(module_path.read_text())

        imported_top_levels: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_top_levels.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_top_levels.add(node.module.split(".")[0])

        offenders = imported_top_levels & self._FORBIDDEN_MODULES
        assert not offenders, (
            f"trajectory.py imports networked module(s) {offenders} -- Trajectories "
            "must never leave the machine (ADR 0001)"
        )


class TestCaptureDiff:
    """AC 4, AC 5: a Slice's diff is captured from the repo on disk
    against the commit it started from. These run against a real,
    throwaway git repo (never the actual working tree this suite runs
    from) but never touch Docker -- see this module's module docstring
    for why diff capture reads the host side of the bind mount directly
    rather than going through a Sandbox."""

    def test_no_changes_returns_the_empty_string(self, git_repo: tuple[Path, str]) -> None:
        repo, base = git_repo

        assert capture_diff(repo, base) == ""

    def test_editing_a_tracked_file_produces_a_non_empty_diff(
        self, git_repo: tuple[Path, str]
    ) -> None:
        repo, base = git_repo
        (repo / "tracked.txt").write_text("changed\n")

        diff = capture_diff(repo, base)

        assert diff != ""
        assert "tracked.txt" in diff
        assert "changed" in diff

    def test_a_new_file_is_captured(self, git_repo: tuple[Path, str]) -> None:
        # A model that creates a wholly new file is one of the most
        # common Slice shapes there is; a diff mechanism that silently
        # drops untracked paths would make AC 6 a lie for that shape.
        # Plain `git diff` never shows untracked paths on its own -- see
        # this module's docstring for the `git add -N` (intent-to-add)
        # mechanism capture_diff is required to use, and the documented,
        # deliberate index-mutation side effect that comes with it.
        repo, base = git_repo
        (repo / "new_file.txt").write_text("brand new\n")

        diff = capture_diff(repo, base)

        assert diff != ""
        assert "new_file.txt" in diff

    def test_a_gitignored_file_is_never_captured(self, git_repo: tuple[Path, str]) -> None:
        # The intent-to-add mechanism that makes new_file.txt visible
        # above must not reach into .gitignore'd paths -- `git add -N`
        # over `git ls-files --others --exclude-standard` (not a bare
        # `git add -A .`) is what keeps that boundary intact.
        repo, base = git_repo
        (repo / ".gitignore").write_text("ignored.txt\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "add gitignore")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "ignored.txt").write_text("should never appear\n")

        diff = capture_diff(repo, base)

        assert "ignored.txt" not in diff

    def test_diff_respects_the_given_base_commit_not_just_head(
        self, git_repo: tuple[Path, str]
    ) -> None:
        repo, base = git_repo
        (repo / "tracked.txt").write_text("first change\n")
        _git(repo, "commit", "-am", "first change")
        second_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "tracked.txt").write_text("second change\n")

        diff_from_base = capture_diff(repo, base)
        diff_from_second_commit = capture_diff(repo, second_commit)

        # Against the Slice's actual starting commit, both changes show.
        assert "first change" in diff_from_base
        assert "second change" in diff_from_base
        # Against the later commit, only the change made after it shows.
        assert "first change" not in diff_from_second_commit
        assert "second change" in diff_from_second_commit

    def test_captured_diff_never_contains_a_sandbox_exit_status_artifact(
        self, git_repo: tuple[Path, str]
    ) -> None:
        # Guards the pitfall named in trajectory.py's module docstring:
        # `git diff --exit-code` exits 1 when there are changes, which
        # would look like an ordinary command failure if this were ever
        # run through Sandbox.run (issue #14 appends a literal "exit
        # status: <n>" element to `content` on any nonzero exit).
        repo, base = git_repo
        (repo / "tracked.txt").write_text("changed\n")

        diff = capture_diff(repo, base)

        assert "exit status:" not in diff


class TestCaptureDiffFromSandboxBindMount:
    """AC 6: the diff is captured from the Sandbox's bind-mounted repo,
    not from what the model claimed it did. Proven end-to-end against
    real Docker: a container writes a file, the Sandbox is closed, and
    capture_diff (which never touches Docker itself) still sees the
    change because the bind mount put it on the host path directly."""

    def test_a_change_made_inside_the_container_is_captured_on_the_host(
        self, git_repo: tuple[Path, str]
    ) -> None:
        repo, base = git_repo
        config = SandboxConfig(repo_path=repo, timeout_seconds=10.0, memory_limit="128m")

        with Sandbox(config) as sb:
            result = sb.run(
                ToolCall(
                    call_id="c1",
                    name="shell",
                    arguments={
                        "command": (f"echo container-wrote-this >> {config.mount_path}/tracked.txt")
                    },
                )
            )
        assert result.outcome is Outcome.OK

        diff = capture_diff(repo, base)

        assert "container-wrote-this" in diff
        assert "exit status:" not in diff


class TestSandboxCapTripSurfacesAsFailedTrajectory:
    """AC 8: a Sandbox container killed on its timeout surfaces as a
    failed Trajectory -- the trip is not silently dropped. Real Docker,
    a single run() on the tripped Sandbox only (issue #14 review: a
    second run() after a trip misreports via the latched OOMKilled
    flag), and diff capture afterwards uses no Sandbox at all, so the
    tripped container's state cannot affect it."""

    def test_a_wall_clock_trip_surfaces_as_a_failed_trajectory(
        self, git_repo: tuple[Path, str]
    ) -> None:
        repo, base = git_repo
        config = SandboxConfig(repo_path=repo, timeout_seconds=1.0, memory_limit="128m")
        call = ToolCall(call_id="c1", name="shell", arguments={"command": "sleep 30"})

        with Sandbox(config) as sb:
            tripped_result = sb.run(call)

        assert tripped_result.outcome is Outcome.ERROR
        assert "timeout" in "".join(tripped_result.content).lower()

        diff = capture_diff(repo, base)

        trajectory = Trajectory(
            tool_calls=(call,),
            tool_results=(tripped_result,),
            diff=diff,
            gate_command_result=ToolResult(
                outcome=Outcome.ERROR,
                content=("gate did not run: Slice attempt errored before completion",),
            ),
            gate_verdict=GateVerdict.FAIL,
            termination_reason=TerminationReason.HARNESS_ERROR,
            cost=0.0,
            duration_seconds=1.0,
        )

        assert trajectory.tool_results == (tripped_result,)
        assert trajectory.gate_verdict is GateVerdict.FAIL
        assert trajectory.diff == ""  # `sleep 30` made no filesystem changes


class TestWriteTrajectory:
    """AC 1, AC 2, AC 3, AC 9: pins the on-disk JSON shape documented in
    write_trajectory's docstring. The implement stage owns the body;
    these tests own the format."""

    def test_persists_json_with_the_documented_shape(self, tmp_path: Path) -> None:
        traj = _full_trajectory()
        out = tmp_path / "trajectory.json"

        write_trajectory(traj, out)

        data = json.loads(out.read_text())
        assert data["termination_reason"] == "model-finished"
        assert data["gate_verdict"] == "pass"
        assert data["diff"] == ""
        assert data["cost"] == traj.cost
        assert data["duration_seconds"] == traj.duration_seconds
        assert data["tool_calls"][0]["call_id"] == "c1"
        assert data["tool_calls"][0]["name"] == "shell"
        assert data["tool_results"][0]["outcome"] == "ok"
        assert data["gate_command_result"]["outcome"] == "ok"

    def test_empty_diff_is_a_present_key_not_a_missing_one(self, tmp_path: Path) -> None:
        traj = _full_trajectory(diff="")
        out = tmp_path / "trajectory.json"

        write_trajectory(traj, out)

        data = json.loads(out.read_text())
        assert "diff" in data
        assert data["diff"] == ""

    def test_non_empty_diff_round_trips_verbatim(self, tmp_path: Path) -> None:
        raw_diff = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
        traj = _full_trajectory(diff=raw_diff)
        out = tmp_path / "trajectory.json"

        write_trajectory(traj, out)

        data = json.loads(out.read_text())
        assert data["diff"] == raw_diff

    def test_failing_gate_trajectory_writes_every_field(self, tmp_path: Path) -> None:
        traj = _full_trajectory(
            gate_verdict=GateVerdict.FAIL,
            gate_command_result=ToolResult(outcome=Outcome.OK, content=("2 failed",)),
        )
        out = tmp_path / "trajectory.json"

        write_trajectory(traj, out)

        data = json.loads(out.read_text())
        expected_keys = {
            "tool_calls",
            "tool_results",
            "diff",
            "gate_command_result",
            "gate_verdict",
            "termination_reason",
            "cost",
            "duration_seconds",
        }
        assert expected_keys <= data.keys()
        assert data["gate_verdict"] == "fail"

    def test_errored_before_completion_trajectory_writes_every_field(self, tmp_path: Path) -> None:
        traj = Trajectory(
            tool_calls=(),
            tool_results=(
                ToolResult(outcome=Outcome.ERROR, content=("harness crashed: OSError",)),
            ),
            diff="",
            gate_command_result=ToolResult(
                outcome=Outcome.ERROR,
                content=("gate did not run: Slice attempt errored before completion",),
            ),
            gate_verdict=GateVerdict.FAIL,
            termination_reason=TerminationReason.HARNESS_ERROR,
            cost=0.004,
            duration_seconds=3.1,
        )
        out = tmp_path / "trajectory.json"

        write_trajectory(traj, out)

        data = json.loads(out.read_text())
        assert data["tool_calls"] == []
        assert data["termination_reason"] == "harness-error"
        assert data["gate_verdict"] == "fail"
        assert data["gate_command_result"]["outcome"] == "error"
