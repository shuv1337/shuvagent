from __future__ import annotations

from shuvagent.doctor import DoctorCheck, doctor_exit_code, format_doctor_checks

ISSUE1_CLOSURE_GATES: tuple[str, ...] = (
    "Spoken microphone input through `shuvagent run` + `shuvagent control start`.",
    "Audible model speech through the default speaker.",
    "Spoken selected-text Q&A using real `wl-paste --primary` selected text.",
)


def format_issue1_qa(checks: list[DoctorCheck]) -> str:
    lines = [
        "Issue #1 live QA preflight",
        "",
        format_doctor_checks(checks),
        "",
        "Closure gates requiring target-desktop human/hardware evidence:",
    ]
    lines.extend(f"- [ ] {gate}" for gate in ISSUE1_CLOSURE_GATES)
    lines.extend(
        [
            "",
            "Record only safe evidence: control outputs, event names, structured "
            "reasons, and whether audio was heard. Do not record transcripts, raw "
            "selected text, clipboard contents, or API keys.",
        ]
    )
    return "\n".join(lines)


def issue1_qa_exit_code(checks: list[DoctorCheck]) -> int:
    return doctor_exit_code(checks)
