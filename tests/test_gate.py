"""Tests for Test Gate layer 1: running the Gate Command in the Sandbox
(issue #17; CONTEXT.md's "Gate Command" entry; ADR 0007 is context, not
scope here — its rule logic is issue #18, exercised against this module's
output, not against Sandbox or Trajectory directly).

External behaviour only, mirroring test_sandbox.py's and test_trajectory.py's
conventions: nothing here mocks Docker — every test that runs a Gate Command
starts a real local container, and every direct `docker`/`git` CLI call this
file makes itself carries a hard timeout so a hang here cannot stall the
suite. Before `run_gate_command`'s implementation exists, every behavioural
test below fails fast on `NotImplementedError`, before touching Docker at
all -- there is nothing to hang on yet.

Per issue #25 (open defect: `State.OOMKilled` latches in the Docker API
response, so a memory-cap trip can be misattributed to a later, unrelated
`run()` on the same container), the wall-clock timeout -- not the memory cap
-- is used here to exercise the "Gate Command never completed" case, and
each `Sandbox` in this file makes at most one `run()` call after a trip.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from ryai_harness.gate import GateCommand, GateRun, run_gate_command
from ryai_harness.sandbox import Sandbox, SandboxConfig
from ryai_harness.tool_result import Outcome, ToolResult
from ryai_harness.trajectory import GateVerdict, TerminationReason, Trajectory

# Small placeholder caps, matching test_sandbox.py's discipline: generous
# enough for a plain shell one-liner, tight enough that a trip resolves in
# seconds.
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MEMORY_LIMIT = "128m"

# Hard ceiling on any `docker` CLI call this file makes directly, independent
# of whatever timeout Sandbox enforces internally.
DOCKER_CLI_TIMEOUT = 15


def _docker(*args: str, timeout: int = DOCKER_CLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a `docker` CLI command with a hard timeout. Never mocked."""
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _output(result: ToolResult) -> str:
    return "".join(result.content)


@pytest.fixture(scope="session", autouse=True)
def _pull_sandbox_image() -> None:
    # Pre-pull so a cold image pull can never be what makes a test in this
    # file look slow or hung.
    _docker("pull", SandboxConfig().image, timeout=120)


@pytest.fixture(scope="module", autouse=True)
def _no_sandbox_containers_survive_the_module() -> Iterator[None]:
    """Same leak-sweep discipline as test_sandbox.py: after every test in
    this module has run, zero containers carrying Sandbox's label may
    remain."""
    yield

    leaked = _docker("ps", "-aq", "--filter", f"label={Sandbox.CONTAINER_LABEL}")
    assert leaked.returncode == 0
    leaked_ids = leaked.stdout.split()
    if leaked_ids:
        _docker("rm", "-f", *leaked_ids)  # clean up before failing
    assert leaked_ids == [], f"sandbox containers outlived their test: {leaked_ids}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo directory standing in for the real one. Tests must
    never bind-mount the actual working tree they run from."""
    (tmp_path / "marker.txt").write_text("host-authored\n")
    return tmp_path


@pytest.fixture
def sandbox_config(repo: Path) -> SandboxConfig:
    return SandboxConfig(
        repo_path=repo,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        memory_limit=DEFAULT_MEMORY_LIMIT,
    )


class TestGateCommandShape:
    """`GateCommand` is plain configuration data -- no path, no repo
    reference (AC: a Slice cannot change which command grades it)."""

    def test_holds_the_command_string(self) -> None:
        gc = GateCommand(command="pytest -q")
        assert gc.command == "pytest -q"

    def test_is_frozen(self) -> None:
        gc = GateCommand(command="pytest -q")
        with pytest.raises(AttributeError):
            gc.command = "echo pwned"  # type: ignore[misc]

    def test_command_field_has_no_default(self) -> None:
        with pytest.raises(TypeError):
            GateCommand()  # type: ignore[call-arg]


class TestGateRunShape:
    """`GateRun` is layer 1's output: the raw `ToolResult` verbatim, plus a
    decoded `exit_code` so layer 2 (#18) never parses `ToolResult.content`
    itself."""

    def test_holds_tool_result_and_exit_code(self) -> None:
        tr = ToolResult(outcome=Outcome.OK, content=("3 passed",))
        run = GateRun(tool_result=tr, exit_code=0)
        assert run.tool_result is tr
        assert run.exit_code == 0

    def test_exit_code_admits_none_for_a_command_that_never_completed(self) -> None:
        tr = ToolResult(
            outcome=Outcome.ERROR,
            content=("tool call exceeded the sandbox timeout of 5.0s",),
        )
        run = GateRun(tool_result=tr, exit_code=None)
        assert run.exit_code is None

    def test_is_frozen(self) -> None:
        run = GateRun(tool_result=ToolResult(outcome=Outcome.OK), exit_code=0)
        with pytest.raises(AttributeError):
            run.exit_code = 1  # type: ignore[misc]


class TestGateRunOutcomeExitCodeInvariant:
    """Issue #18's resolving comment on #17's review finding #2: `GateRun`
    construction must enforce that `outcome` and `exit_code` agree,
    mirroring `ToolResult`'s own cross-field-invariant pattern
    (`__post_init__`, not left to callers). A gate that reports pass while
    the underlying process exited nonzero -- or vice versa -- must fail to
    construct, not silently propagate."""

    def test_ok_outcome_with_no_exit_code_is_rejected(self) -> None:
        tr = ToolResult(outcome=Outcome.OK, content=("2 passed",))
        with pytest.raises(ValueError):
            GateRun(tool_result=tr, exit_code=None)

    def test_non_ok_outcome_with_an_exit_code_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            GateRun(
                tool_result=ToolResult(outcome=Outcome.ERROR, content=("timed out",)),
                exit_code=0,
            )


class TestGateRunFeedsTrajectory:
    """The seam #18 (and whatever assembles a Trajectory) builds against:
    `GateRun.tool_result` must be directly assignable to
    `Trajectory.gate_command_result` with no adapter -- proven here without
    Docker, using a hand-built `ToolResult` the way #16's own tests do."""

    def test_gate_run_tool_result_is_trajectory_shaped(self) -> None:
        # Sandbox.run appends "exit status: n" only when returncode != 0
        # (see sandbox.py); an exit-0 result is a single-element content
        # tuple, so this fixture must not invent a suffix that would never
        # actually appear alongside a passing exit code.
        tr = ToolResult(outcome=Outcome.OK, content=("2 passed",))
        run = GateRun(tool_result=tr, exit_code=0)

        trajectory = Trajectory(
            tool_calls=(),
            tool_results=(),
            diff="",
            gate_command_result=run.tool_result,
            gate_verdict=GateVerdict.PASS,
            termination_reason=TerminationReason.MODEL_FINISHED,
            cost=0.0,
            duration_seconds=1.0,
        )

        assert trajectory.gate_command_result is run.tool_result


class TestRunGateCommandNeverReadsModelOutput:
    """Structural guard for the AC that layer 1 decides nothing from model
    output: `run_gate_command`'s signature admits only a `Sandbox` and a
    `GateCommand`, and this module never reads a file (it has no path to
    read one from in the first place)."""

    def test_signature_has_only_sandbox_and_gate_command(self) -> None:
        params = list(inspect.signature(run_gate_command).parameters)
        assert params == ["sandbox", "gate_command"]

    def test_module_never_opens_or_reads_a_file(self) -> None:
        import ryai_harness.gate as gate_module

        source = inspect.getsource(gate_module)
        tree = ast.parse(source)

        file_reading_names = {"open", "read_text", "read_bytes", "read", "readlines"}
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id in file_reading_names)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in file_reading_names)
            )
        ]
        assert offenders == [], (
            "gate.py must never read a file -- the Gate Command is configuration"
        )


class TestRunGateCommandInSandbox:
    """AC: the configured Gate Command runs inside the Sandbox's container,
    never on the host; a passing fixture command records the expected
    result (AC: exit code 0); at least one real end-to-end run against a
    real container (AC)."""

    def test_runs_in_the_container_and_records_a_passing_exit_code(
        self, sandbox_config: SandboxConfig
    ) -> None:
        with Sandbox(sandbox_config) as sb:
            expected_hostname = sb.container_id[:12]
            gate_command = GateCommand(command="hostname; exit 0")
            run = run_gate_command(sb, gate_command)

        assert run.tool_result.outcome is Outcome.OK
        assert expected_hostname in _output(run.tool_result)
        assert run.exit_code == 0

    def test_exit_zero_whose_only_output_looks_like_the_suffix_decodes_as_zero(
        self, sandbox_config: SandboxConfig
    ) -> None:
        # The mirror of TestFailingGateCommand's decoy case, and the one the
        # arity check in _decode_exit_code exists for. Here the lookalike is
        # the command's *entire* output, so it lands in content's last (and
        # only) element -- exactly where the real suffix would sit. Position
        # alone cannot tell them apart; the element count can, because
        # Sandbox.run appends its suffix as a second element and does so
        # only on a non-zero exit. Without that arity guard this decodes as
        # 42 and a passing Gate Command reads as a failing one.
        gate_command = GateCommand(command='echo "exit status: 42"; exit 0')

        with Sandbox(sandbox_config) as sb:
            run = run_gate_command(sb, gate_command)

        assert run.tool_result.outcome is Outcome.OK
        assert "exit status: 42" in _output(run.tool_result)
        assert run.exit_code == 0


class TestFailingGateCommand:
    """AC: a fixture Gate Command exiting non-zero records the expected
    result, with combined stdout/stderr captured."""

    def test_records_nonzero_exit_code_and_combined_output(
        self, sandbox_config: SandboxConfig
    ) -> None:
        # The command's own output deliberately contains text that looks
        # like the "exit status: n" suffix Sandbox.run appends -- pins that
        # exit_code is decoded from the suffix's position (the last
        # element), not by substring-searching the whole output.
        gate_command = GateCommand(
            command='echo out-line; echo "exit status: 99"; echo err-line 1>&2; exit 7'
        )

        with Sandbox(sandbox_config) as sb:
            run = run_gate_command(sb, gate_command)

        assert run.tool_result.outcome is Outcome.OK
        output = _output(run.tool_result)
        assert "out-line" in output
        assert "err-line" in output
        assert run.exit_code == 7


class TestGateCommandThatNeverCompletes:
    """The third case, beyond exit-0 and exit-nonzero: the Sandbox's
    wall-clock cap trips before the Gate Command finishes. This must not be
    confused with a passing or failing exit -- there is no exit code to
    report, not a missing one."""

    def test_wall_clock_trip_surfaces_as_error_with_no_exit_code(self, repo: Path) -> None:
        config = SandboxConfig(
            repo_path=repo, timeout_seconds=1.0, memory_limit=DEFAULT_MEMORY_LIMIT
        )
        gate_command = GateCommand(command="sleep 30")

        with Sandbox(config) as sb:
            run = run_gate_command(sb, gate_command)

        assert run.tool_result.outcome is Outcome.ERROR
        assert run.exit_code is None


class TestGateCommandGradingFixedAtSliceStart:
    """AC: a Slice cannot change which Gate Command grades it, including by
    editing files in the mounted repo mid-Slice.

    This is a genuine differential test, not ceremony: `run_gate_command`
    receives the `Sandbox` itself, and `sandbox_config.repo_path` /
    `mount_path` are reachable from it -- so an implementation that
    re-derived the command string from the mounted repo at call time,
    instead of using the `GateCommand` it was handed, is a real failure
    mode this signature does not rule out on its own.
    `TestRunGateCommandNeverReadsModelOutput` above pins that this module's
    own source never reads a file; this test pins the same thing
    behaviourally, at the seam #18 will call. The mounted repo is made to
    hold a *different* command ("exit 1") than the one already captured
    ("exit 0") before `run_gate_command` is even called -- a correct
    implementation is inert to the edit; a re-reading one is not.
    (If the Gate Command's own logic reads a repo file -- e.g. `sh
    gate.sh` -- editing that file legitimately changes what running the
    command does; that is a property of the command being run, not of
    which command runs, and is not what this AC is about.)
    """

    def test_editing_the_config_source_mid_slice_does_not_change_the_command_that_runs(
        self, sandbox_config: SandboxConfig, repo: Path
    ) -> None:
        config_file = repo / "gate_command.txt"
        config_file.write_text("exit 0")

        # Simulates the Harness reading its configuration once, at Slice
        # start, before any Slice work happens: the command text is
        # captured as a plain string, decoupled from the file it came from.
        gate_command = GateCommand(command=config_file.read_text().strip())

        with Sandbox(sandbox_config) as sb:
            # Mid-Slice: the model (stood in for here by a direct write, as
            # if a tool call had done it) edits the very file the command
            # text was originally sourced from, trying to weaken the bar
            # for whatever runs next.
            config_file.write_text("exit 1")

            run = run_gate_command(sb, gate_command)

        # The already-captured GateCommand still holds "exit 0" -- the
        # string, not a reference to the file -- so the edit to the file
        # that happened after capture has no effect on what ran.
        assert run.exit_code == 0
