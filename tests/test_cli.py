from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from shuvagent import cli
from shuvagent.cli import _reload_config, _SessionRunner, _start_decision
from shuvagent.config import AppConfig
from shuvagent.coordination import Decision
from shuvagent.doctor import DoctorCheck
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.usage import UsageTracker


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


def test_issue1_qa_command_prints_closure_gates(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda config_path: [DoctorCheck("config", "pass", "ok")],
    )

    assert cli.main(["issue1-qa"]) == 0

    output = capsys.readouterr().out
    assert "Issue #1 live QA preflight" in output
    assert "PASS config: ok" in output
    assert "Closure gates requiring target-desktop" in output
    assert "Spoken microphone input" in output


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
        statuses: list[str] = []
        runner = _SessionRunner(
            config=AppConfig(),
            api_key="sk-test",
            sink=sink,
            status_writer=statuses.append,
        )
        finished: list[str] = []

        async def fake_run_session(stop_event: asyncio.Event) -> None:
            await stop_event.wait()
            finished.append(runner._session_id or "")

        runner._run_session = fake_run_session

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
        assert statuses == [
            "[shuvagent] Session started: control start",
            "[shuvagent] Session stopped: session ended",
        ]

    asyncio.run(run())


def test_session_runner_stop_is_bounded_and_force_cancels_stuck_session() -> None:
    """handle_stop must return within the bound and force-cancel a session
    that ignores stop_event (the 'graceful but bounded' guarantee, US23)."""

    async def run() -> None:
        sink = MemorySink()
        runner = _SessionRunner(
            config=AppConfig(),
            api_key="sk-test",
            sink=sink,
            stop_timeout_sec=0.05,
        )

        async def stuck_run_session(stop_event: asyncio.Event) -> None:
            del stop_event  # deliberately ignore the cooperative stop signal
            await asyncio.Event().wait()  # never returns on its own

        runner._run_session = stuck_run_session

        await runner.handle_start("session-stuck")
        task = runner._task
        assert task is not None

        loop = asyncio.get_running_loop()
        before = loop.time()
        await runner.handle_stop("session-stuck")
        elapsed = loop.time() - before

        # Bounded: returns well within a small multiple of the stop timeout.
        assert elapsed < 2.0
        # Force-cancelled: the stuck task did not finish on its own.
        assert task.cancelled()
        assert runner._task is None
        assert runner._stop_event is None
        assert runner._session_id is None

    asyncio.run(run())


def test_reload_config_applies_safety_caps_to_runner(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[realtime]
session_max_duration_sec = 7
output_token_cap = 123
voice = "cedar"
"""
    )
    sink = MemorySink()
    runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)
    runner._usage_tracker = UsageTracker(output_token_cap=800)

    assert _reload_config(config_path, runner, sink)

    assert runner._config.realtime.session_max_duration_sec == 7
    assert runner._config.realtime.output_token_cap == 123
    assert runner._config.realtime.voice == "cedar"
    assert runner._usage_tracker.output_token_cap == 123
    assert sink.events[-1].event == "app.lifecycle.config_reloaded"
    assert sink.events[-1].attributes == {
        "session_max_duration_sec": 7,
        "output_token_cap": 123,
    }


def test_reload_config_keeps_old_config_when_invalid(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[realtime]
voice = "invalid"
"""
    )
    sink = MemorySink()
    runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)

    assert not _reload_config(config_path, runner, sink)

    assert runner._config == AppConfig()
    assert sink.events[-1].event == "app.lifecycle.config_reload_failed"
    assert sink.events[-1].level == "error"


def test_reload_config_logs_voice_deferred_during_active_session(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            """
[realtime]
voice = "cedar"
"""
        )
        sink = MemorySink()
        runner = _SessionRunner(config=AppConfig(), api_key="sk-test", sink=sink)

        async def fake_run_session(stop_event: asyncio.Event) -> None:
            await stop_event.wait()

        runner._run_session = fake_run_session
        await runner.handle_start("session-1")
        try:
            assert _reload_config(config_path, runner, sink)
        finally:
            await runner.handle_stop("session-1")

        assert any(
            event.event == "app.lifecycle.config_reload_voice_deferred"
            and event.attributes == {"old_voice": "marin", "new_voice": "cedar"}
            for event in sink.events
        )

    asyncio.run(run())


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
