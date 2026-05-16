from __future__ import annotations

from shuvagent.doctor import DoctorCheck
from shuvagent.live_qa import (
    ISSUE1_CLOSURE_GATES,
    format_issue1_qa,
    issue1_qa_exit_code,
)


def test_format_issue1_qa_includes_doctor_and_closure_gates() -> None:
    checks = [DoctorCheck("config", "pass", "ok")]

    output = format_issue1_qa(checks)

    assert "PASS config: ok" in output
    for gate in ISSUE1_CLOSURE_GATES:
        assert f"- [ ] {gate}" in output
    assert "Do not record transcripts" in output


def test_issue1_qa_exit_code_follows_doctor_failures() -> None:
    assert issue1_qa_exit_code([DoctorCheck("config", "pass", "ok")]) == 0
    assert issue1_qa_exit_code([DoctorCheck("config", "fail", "bad")]) == 1
