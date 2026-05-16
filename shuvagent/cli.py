from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

from shuvagent.app import ConversationApp
from shuvagent.audio.runtime import (
    AudioRuntimeError,
    audio_runtime_error,
    enqueue_audio_chunk,
    report_audio_status,
)
from shuvagent.config import AppConfig, load_config
from shuvagent.control import ControlServer, send_control_command
from shuvagent.coordination import (
    Decision,
    PausableSession,
    can_start_agent_session,
    monitor_shuvoice,
    shuvoice_tts_stop,
)
from shuvagent.doctor import doctor_exit_code, format_doctor_checks, run_doctor
from shuvagent.env_loader import load_env_file
from shuvagent.paths import default_local_env_path
from shuvagent.realtime.openai_session import (
    OpenAIRealtimeSession,
    OpenAISessionConfig,
)
from shuvagent.telemetry.schema import TelemetryEvent
from shuvagent.telemetry.sink import JsonLineSink
from shuvagent.tools.builtins import default_read_only_tools
from shuvagent.tools.policy import PermissionGate
from shuvagent.tools.registry import ToolRegistry
from shuvagent.usage import UsageTracker
from shuvagent.window import get_active_window


class _RawOutputStream(Protocol):
    def start(self) -> None: ...
    def write(self, data: bytes) -> None: ...


class _RawInputStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class _TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        try:
            return asyncio.run(_run(args.config))
        except KeyboardInterrupt:
            return 130
    if args.command == "control":
        return asyncio.run(_control(args.verb, args.config))
    if args.command == "doctor":
        checks = run_doctor(args.config)
        print(format_doctor_checks(checks))
        return doctor_exit_code(checks)
    if args.command in {"start", "stop", "status"}:
        return asyncio.run(_control(args.command, args.config))
    parser.error(f"unknown command {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shuvagent")
    parser.add_argument("--config", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="run the foreground shuvagent process")
    control = subparsers.add_parser("control", help="send a control command")
    control.add_argument("verb", choices=["start", "stop", "status"])
    subparsers.add_parser("doctor", help="check live validation prerequisites")
    subparsers.add_parser("start", help="alias for control start")
    subparsers.add_parser("stop", help="alias for control stop")
    subparsers.add_parser("status", help="alias for control status")
    return parser


async def _run(config_path: Path | None) -> int:
    config = load_config(config_path)
    loaded = load_env_file(default_local_env_path())
    sink = JsonLineSink(debug_log_raw_text=config.telemetry.debug_log_raw_text)
    sink.emit(
        TelemetryEvent(
            event="app.lifecycle.start",
            attributes={"env_vars_loaded": loaded},
        )
    )

    api_key = os.environ.get(config.realtime.api_key_env)
    runner = _SessionRunner(config=config, api_key=api_key, sink=sink)

    server = ControlServer(
        config.control.socket,
        start_decision=_start_decision(config=config, api_key=api_key),
        on_start=runner.handle_start,
        on_stop=runner.handle_stop,
    )
    runner.on_session_finished = server.finish_session
    await server.start()
    print(f"[shuvagent] Loaded {loaded} env var(s) from {default_local_env_path()}")
    print(f"[shuvagent] Control socket: {config.control.socket}")
    if api_key:
        print(f"[shuvagent] Using live realtime backend ({config.realtime.model}).")
    else:
        print(
            "[shuvagent] No API key in $"
            f"{config.realtime.api_key_env}; control start will be denied."
        )
    print("[shuvagent] Ready.")
    sink.emit(TelemetryEvent(event="app.lifecycle.ready"))
    try:
        await server.serve_forever()
    finally:
        await runner.shutdown()
        await server.stop()
        sink.emit(TelemetryEvent(event="app.lifecycle.stop"))
    return 0


def _start_decision(
    *, config: AppConfig, api_key: str | None
) -> Callable[[], Decision]:
    def decide() -> Decision:
        if not api_key:
            return Decision.deny(f"missing_api_key:{config.realtime.api_key_env}")
        return can_start_agent_session(
            timeout=config.coordination.shuvoice_control_timeout_sec,
        )

    return decide


async def _control(verb: str, config_path: Path | None) -> int:
    config = load_config(config_path)
    response = await send_control_command(config.control.socket, verb)
    print(response)
    return 0 if response.startswith("OK ") else 1


class _SessionRunner:
    """Bridge between the control socket and a streaming ConversationApp.

    Holds at most one active session at a time. ``handle_start`` is
    fire-and-forget — the actual session lives in a background task so
    the control socket stays responsive.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        api_key: str | None,
        sink: _TelemetrySink,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._sink = sink
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._session_id: str | None = None
        self.on_session_finished: Callable[[str], None] | None = None

    async def handle_start(self, session_id: str) -> None:
        if self._task is not None and not self._task.done():
            return
        self._session_id = session_id
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_session_until_finished(session_id, self._stop_event)
        )

    async def handle_stop(self, session_id: str) -> None:
        del session_id
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, Exception):
                self._task.cancel()
        self._task = None
        self._stop_event = None
        self._session_id = None

    async def shutdown(self) -> None:
        await self.handle_stop(self._session_id or "")

    async def _run_session_until_finished(
        self,
        session_id: str,
        stop_event: asyncio.Event,
    ) -> None:
        try:
            await self._run_session(stop_event)
        finally:
            if self._session_id == session_id:
                self._session_id = None
                self._stop_event = None
                if self.on_session_finished is not None:
                    self.on_session_finished(session_id)

    async def _run_session(self, stop_event: asyncio.Event) -> None:
        if self._api_key is None:
            self._sink.emit(
                TelemetryEvent(
                    event="agent.session.failed",
                    attributes={"reason": "missing_api_key"},
                )
            )
            return

        self._stop_shuvoice_tts()
        registry = ToolRegistry(window_snapshot=get_active_window)
        tool_specs = default_read_only_tools()
        for spec in tool_specs:
            registry.register(spec)
        gate = PermissionGate(registry.specs(), window_snapshot=get_active_window)

        session = OpenAIRealtimeSession(
            OpenAISessionConfig(
                api_key=self._api_key,
                model=self._config.realtime.model,
                voice=self._config.realtime.voice,
                reasoning_effort=self._config.realtime.reasoning_effort,
                tools=tuple(tool_specs),
                max_output_tokens=self._config.realtime.output_token_cap,
                request_timeout_sec=self._config.realtime.request_timeout_sec,
            )
        )
        app = ConversationApp(
            session=session, registry=registry, gate=gate
        )
        capture_pause = _CapturePauseController()
        monitored_session = _MicReleaseSession(session, capture_pause)

        duration_task = asyncio.create_task(
            self._stop_after_duration_cap(stop_event)
        )
        try:
            await app.run_streaming(
                audio_in=_mic_stream(
                    stop_event,
                    self._config,
                    self._sink.emit,
                    pause_controller=capture_pause,
                ),
                playback=_speaker_playback(self._config),
                stop_event=stop_event,
                event_sink=self._sink.emit,
                usage_tracker=UsageTracker(
                    output_token_cap=self._config.realtime.output_token_cap
                ),
                session_monitors=[
                    lambda: monitor_shuvoice(
                        monitored_session,
                        interval_sec=self._config.coordination.shuvoice_status_poll_sec,
                        timeout=self._config.coordination.shuvoice_control_timeout_sec,
                        event_sink=self._emit_shuvoice_arbitration,
                    )
                ],
            )
        except Exception as exc:  # pragma: no cover - runtime failure path
            self._emit_session_failure(exc)
        finally:
            duration_task.cancel()
            await asyncio.gather(duration_task, return_exceptions=True)

    def _emit_session_failure(self, exc: Exception) -> None:
        if isinstance(exc, AudioRuntimeError):
            self._sink.emit(
                TelemetryEvent(
                    event="audio.device_error",
                    level="error",
                    attributes={
                        "code": exc.code,
                        "message": exc.safe_message,
                    },
                )
            )
        self._sink.emit(
            TelemetryEvent(
                event="agent.session.failed",
                level="error",
                attributes={"error": str(exc)},
            )
        )

    def _stop_shuvoice_tts(self) -> None:
        ok = shuvoice_tts_stop(
            timeout=self._config.coordination.shuvoice_control_timeout_sec,
        )
        self._sink.emit(
            TelemetryEvent(
                event="shuvoice.tts_stop_requested",
                level="info" if ok else "warning",
                attributes={"ok": ok},
            )
        )

    def _emit_shuvoice_arbitration(self, action: str, reason: str) -> None:
        self._sink.emit(
            TelemetryEvent(
                event="shuvoice.mic_arbitration",
                attributes={"action": action, "reason": reason},
            )
        )

    async def _stop_after_duration_cap(self, stop_event: asyncio.Event) -> None:
        await asyncio.sleep(self._config.realtime.session_max_duration_sec)
        if stop_event.is_set():
            return
        self._sink.emit(
            TelemetryEvent(
                event="agent.session.interrupted",
                attributes={
                    "reason": "duration_cap",
                    "duration_cap_sec": self._config.realtime.session_max_duration_sec,
                },
            )
        )
        stop_event.set()


def _speaker_playback(config: AppConfig) -> Callable[[bytes], Awaitable[None]]:
    """Return an async callable that writes PCM16 chunks to the speaker.

    Lazy-imports sounddevice so headless tests don't trigger PortAudio.
    """
    stream: _RawOutputStream | None = None

    async def play(chunk: bytes) -> None:
        nonlocal stream
        if stream is None:
            import sounddevice as sd  # type: ignore[import-untyped]

            try:
                stream = sd.RawOutputStream(
                    samplerate=config.audio.playback_sample_rate,
                    channels=1,
                    dtype="int16",
                    device=None
                    if config.audio.playback_device == "default"
                    else config.audio.playback_device,
                )
                stream.start()
            except Exception as exc:
                raise audio_runtime_error("audio_playback_device_error", exc) from exc
        try:
            stream.write(chunk)
        except Exception as exc:
            raise audio_runtime_error("audio_playback_write_error", exc) from exc

    return play


class _CapturePauseController:
    def __init__(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def pause(self) -> None:
        self._paused = True

    async def resume(self) -> None:
        self._paused = False


class _MicReleaseSession:
    def __init__(
        self,
        session: PausableSession,
        capture_pause: _CapturePauseController,
    ) -> None:
        self._session = session
        self._capture_pause = capture_pause

    @property
    def is_open(self) -> bool:
        return self._session.is_open

    @property
    def is_paused(self) -> bool:
        return self._session.is_paused

    async def pause(self, reason: str) -> None:
        await self._session.pause(reason)
        await self._capture_pause.pause()

    async def resume(self, reason: str) -> None:
        await self._session.resume(reason)
        await self._capture_pause.resume()


async def _mic_stream(
    stop_event: asyncio.Event,
    config: AppConfig,
    event_sink: Callable[[TelemetryEvent], None],
    *,
    pause_controller: _CapturePauseController | None = None,
) -> AsyncIterator[bytes]:
    """Async generator yielding 24kHz PCM16 chunks from the default mic."""
    import sounddevice as sd

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()
    block_frames = 480  # 20 ms at 24kHz
    stream: _RawInputStream | None = None

    def callback(
        indata: bytes,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        del frames, time_info
        if status:
            loop.call_soon_threadsafe(
                report_audio_status,
                event_sink,
                status,
            )
            return
        loop.call_soon_threadsafe(
            enqueue_audio_chunk, queue, bytes(indata), event_sink
        )

    def open_stream() -> _RawInputStream:
        try:
            opened = cast(
                _RawInputStream,
                sd.RawInputStream(
                    samplerate=config.audio.capture_sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=block_frames,
                    device=None
                    if config.audio.capture_device == "default"
                    else config.audio.capture_device,
                    callback=callback,
                ),
            )
            opened.start()
        except Exception as exc:
            raise audio_runtime_error("audio_capture_device_error", exc) from exc
        event_sink(TelemetryEvent(event="audio.capture_start"))
        return opened

    def close_stream(reason: str) -> None:
        nonlocal stream
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        finally:
            stream = None
            event_sink(
                TelemetryEvent(
                    event="audio.capture_stop",
                    attributes={"reason": reason},
                )
            )

    try:
        while not stop_event.is_set():
            if pause_controller is not None and pause_controller.is_paused:
                close_stream("pause")
                await asyncio.sleep(0.05)
                continue
            if stream is None:
                stream = open_stream()
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                continue
            if pause_controller is not None and pause_controller.is_paused:
                continue
            yield chunk
    finally:
        close_stream("stop")
