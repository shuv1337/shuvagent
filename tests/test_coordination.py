import asyncio
import subprocess
from dataclasses import dataclass

from shuvagent.coordination import can_start_agent_session, monitor_shuvoice


def test_allows_when_shuvoice_idle() -> None:
    decision = can_start_agent_session(runner=runner_for({"status": "OK idle"}))

    assert decision.allowed
    assert decision.reason == "shuvoice-idle"


def test_denies_when_shuvoice_recording() -> None:
    decision = can_start_agent_session(runner=runner_for({"status": "OK recording"}))

    assert not decision.allowed
    assert decision.reason == "shuvoice-recording"


def test_allows_after_stopping_shuvoice_tts() -> None:
    calls: list[str] = []

    def runner(args: list[str], timeout: float) -> str:
        del timeout
        calls.append(" ".join(args))
        if args[-1] == "status":
            return "OK tts"
        return "OK stopped"

    decision = can_start_agent_session(runner=runner)

    assert decision.allowed
    assert decision.reason == "shuvoice-tts-stopped"
    assert calls == ["shuvoice control status", "shuvoice control tts_stop"]


def test_allows_when_shuvoice_not_running() -> None:
    def runner(args: list[str], timeout: float) -> str:
        del args, timeout
        raise FileNotFoundError

    decision = can_start_agent_session(runner=runner)

    assert decision.allowed
    assert decision.reason == "shuvoice-not-running"


def test_denies_when_shuvoice_status_times_out() -> None:
    def runner(args: list[str], timeout: float) -> str:
        raise subprocess.TimeoutExpired(args, timeout)

    decision = can_start_agent_session(runner=runner)

    assert not decision.allowed
    assert decision.reason == "shuvoice-status-timeout"


def test_pauses_and_resumes_when_shuvoice_records_mid_session() -> None:
    async def run() -> None:
        session = FakeSession()
        statuses = iter(["OK idle", "OK recording", "OK idle"])
        arbitration_events: list[tuple[str, str]] = []

        def runner(args: list[str], timeout: float) -> str:
            del args, timeout
            return next(statuses, "OK idle")

        task = asyncio.create_task(
            monitor_shuvoice(
                session,
                runner=runner,
                interval_sec=0.01,
                event_sink=lambda action, reason: arbitration_events.append(
                    (action, reason)
                ),
            )
        )
        await asyncio.sleep(0.05)
        session.is_open = False
        await task

        assert session.events == [
            "pause:shuvoice-took-mic",
            "resume:shuvoice-released-mic",
        ]
        assert arbitration_events == [
            ("pause", "shuvoice-took-mic"),
            ("resume", "shuvoice-released-mic"),
        ]

    asyncio.run(run())


def runner_for(responses: dict[str, str]):
    def runner(args: list[str], timeout: float) -> str:
        del timeout
        return responses[args[-1]]

    return runner


@dataclass
class FakeSession:
    is_open: bool = True
    is_paused: bool = False
    events: list[str] | None = None

    def __post_init__(self) -> None:
        self.events = []

    async def pause(self, reason: str) -> None:
        self.is_paused = True
        assert self.events is not None
        self.events.append(f"pause:{reason}")

    async def resume(self, reason: str) -> None:
        self.is_paused = False
        assert self.events is not None
        self.events.append(f"resume:{reason}")
