from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from shuvagent.app import ConversationApp
from shuvagent.config import AppConfig, load_config
from shuvagent.control import ControlServer, send_control_command
from shuvagent.coordination import monitor_shuvoice
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
from shuvagent.window import get_active_window


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        return asyncio.run(_run(args.config))
    if args.command == "control":
        return asyncio.run(_control(args.verb, args.config))
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
        on_start=runner.handle_start,
        on_stop=runner.handle_stop,
    )
    await server.start()
    print(f"[shuvagent] Loaded {loaded} env var(s) from {default_local_env_path()}")
    print(f"[shuvagent] Control socket: {config.control.socket}")
    if api_key:
        print(f"[shuvagent] Using live realtime backend ({config.realtime.model}).")
    else:
        print(
            "[shuvagent] No API key in $"
            f"{config.realtime.api_key_env}; sessions will be no-op stubs."
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
        sink: JsonLineSink,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._sink = sink
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._session_id: str | None = None

    async def handle_start(self, session_id: str) -> None:
        if self._task is not None and not self._task.done():
            return
        self._session_id = session_id
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_session(self._stop_event))

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

    async def _run_session(self, stop_event: asyncio.Event) -> None:
        if self._api_key is None:
            # M1.6 requires an API key; without one, just emit telemetry
            # and exit cleanly so M1.7 read-only tools can still be
            # exercised via the fake session in tests.
            self._sink.emit(
                TelemetryEvent(
                    event="agent.session.failed",
                    attributes={"reason": "missing_api_key"},
                )
            )
            return

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
                request_timeout_sec=self._config.realtime.request_timeout_sec,
            )
        )
        app = ConversationApp(
            session=session, registry=registry, gate=gate
        )

        duration_task = asyncio.create_task(
            self._stop_after_duration_cap(stop_event)
        )
        try:
            await app.run_streaming(
                audio_in=_mic_stream(stop_event, self._config),
                playback=_speaker_playback(self._config),
                stop_event=stop_event,
                event_sink=self._sink.emit,
                session_monitors=[
                    lambda: monitor_shuvoice(
                        session,
                        interval_sec=self._config.coordination.shuvoice_status_poll_sec,
                        timeout=self._config.coordination.shuvoice_control_timeout_sec,
                    )
                ],
            )
        except Exception as exc:  # pragma: no cover - runtime failure path
            self._sink.emit(
                TelemetryEvent(
                    event="agent.session.failed",
                    level="error",
                    attributes={"error": str(exc)},
                )
            )
        finally:
            duration_task.cancel()
            await asyncio.gather(duration_task, return_exceptions=True)

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


def _speaker_playback(config: AppConfig):
    """Return an async callable that writes PCM16 chunks to the speaker.

    Lazy-imports sounddevice so headless tests don't trigger PortAudio.
    """
    state: dict[str, object] = {"stream": None}

    async def play(chunk: bytes) -> None:
        stream = state["stream"]
        if stream is None:
            import sounddevice as sd

            stream = sd.RawOutputStream(
                samplerate=config.audio.playback_sample_rate,
                channels=1,
                dtype="int16",
                device=None
                if config.audio.playback_device == "default"
                else config.audio.playback_device,
            )
            stream.start()
            state["stream"] = stream
        stream.write(chunk)  # type: ignore[union-attr]

    return play


async def _mic_stream(
    stop_event: asyncio.Event, config: AppConfig
) -> AsyncIterator[bytes]:
    """Async generator yielding 24kHz PCM16 chunks from the default mic."""
    import sounddevice as sd

    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()
    block_frames = 480  # 20 ms at 24kHz

    def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
        if status:
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))
        except asyncio.QueueFull:
            pass

    stream = sd.RawInputStream(
        samplerate=config.audio.capture_sample_rate,
        channels=1,
        dtype="int16",
        blocksize=block_frames,
        device=None
        if config.audio.capture_device == "default"
        else config.audio.capture_device,
        callback=callback,
    )
    stream.start()
    try:
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            yield chunk
    finally:
        stream.stop()
        stream.close()
