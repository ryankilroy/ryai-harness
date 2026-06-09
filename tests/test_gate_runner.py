import tempfile
from harness.gate_runner import run_gates


def test_passing_command():
    with tempfile.TemporaryDirectory() as d:
        r = run_gates(d, "true")
        assert r.passed and r.summary == "PASS"


def test_failing_command_captures_output():
    with tempfile.TemporaryDirectory() as d:
        r = run_gates(d, "echo boom >&2; false")
        assert not r.passed
        assert "boom" in r.output
