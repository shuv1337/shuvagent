from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from shuvagent import cli
from shuvagent.cli import _SessionRunner, _start_decision
from shuvagent.config import AppConfig
from shuvagent.coordination import Decision
from shuvagent.doctor import DoctorCheck
from shuvagent.telemetry.schema import TelemetryEvent


def test_run_command_returns_130_on_keyboard_interrupt(monkeypatch) -> None:
    def raise_keyboard_interrupt(coro: Coroutine[Any, Any, int]) -> int:
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", raise_keyboard_interrupt)

    assert cli.main(["run"]) == 130


def test_doctor_command_returns_zero_when_checks_pass(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda config_path: [DoctorCheck("config", "pass", "ok")],
    )

    assert cli.main(["doctor"]) == 0

    assert "PASS config: ok" in capsys.readouterr().out


def test_doctor_command_returns_one_when_check_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda config_path: [DoctorCheck("openai_api_key", "fail", "missing")],
    )

    assert cli.main(["doctor"]) == 1

    assert "FAIL openai_api_key: missing" in capsys.readouterr().out


def test_control_status_command_returns_zero(monkeypatch, capsys) -> None:
    async def fake_send_control_command(socket_path, verb: str) -> str:
        del socket_path
        assert verb == "status"
        return "OK idle"

    monkeypatch.setattr(cli, "load_config", lambda config_path: AppConfig())
    monkeypatch.setattr(cli, "send_control_command", fake_send_control_command)

    assert cli.main(["control", "status"]) == 0

    assert capsys.readouterr().out == "OK idle\n"


def test_status_alias_returns_nonzero_for_control_error(monkeypatch, capsys) -> None:
    async def fake_send_control_command(socket_path, verb: str) -> str:
        del socket_path
        assert verb == "status"
        return "ERROR unavailable"

    monkeypatch.setattr(cli, "load_config", lambda config_path: AppConfig())
    monkeypatch.setattr(cli, "send_control_command", fake_send_control_command)

    assert cli.main(["status"]) == 1

    assert capsys.readouterr().out == "ERROR unavailable\n"


def test_start_decision_denies_missing_key_from_cli_surface() -> None:
    decision = _start_decision(config=AppConfig(), api_key=None)()

    assert decision == Decision.deny("missing_api_key:OPENAI_API_KEY")


def test_session_runner_start_stop_and_shutdown_are_idempotent() -> None:
    async def run() -> None:
        sink = MemorySink()
        runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)
        finished: list[str] = []

        async def fake_run_session_until_finished(
            session_id: str,
            stop_event: asyncio.Event,
        ) -> None:
            await stop_event.wait()
            finished.append(session_id)

        runner._run_session_until_finished = fake_run_session_until_finished

        await runner.handle_start("session-1")
        await runner.handle_start("session-ignored")
        assert runner._task is not None
        assert not runner._task.done()

        await runner.handle_stop("session-1")
        await runner.shutdown()
        await runner.shutdown()

        assert finished == ["session-1"]
        assert runner._task is None
        assert runner._stop_event is None
        assert runner._session_id is None

    asyncio.run(run())


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
