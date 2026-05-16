from __future__ import annotations

from shuvagent.doctor import DoctorCheck, doctor_exit_code, format_doctor_checks

ISSUE1_CLOSURE_GATES: tuple[str, ...] = (
    "Spoken microphone input through `shuvagent run` + `shuvagent control start`.",
    "Audible model speech through the default speaker.",
    "Spoken selected-text Q&A using real `wl-paste --primary` selected text.",
    "Gemini Live/Pipecat session using `GOOGLE_API_KEY` and "
    "`models/gemini-3.1-flash-live-preview`.",
)

ISSUE1_SAFE_EVENTS: tuple[str, ...] = (
    "audio.capture_chunk",
    "realtime.first_audio_response_latency_ms",
    "audio.playback_chunk",
    "tool.requested",
    "tool.executed",
    "agent.session.stopped",
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
            "Expected safe telemetry during the final human run:",
        ]
    )
    lines.extend(f"- {event}" for event in ISSUE1_SAFE_EVENTS)
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
