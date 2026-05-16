from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from shuvagent.paths import default_config_path, default_control_socket_path

REALTIME_VOICES = frozenset(
    {
        "cedar",
        "marin",
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
    }
)
REALTIME_PROVIDERS = frozenset({"openai", "gemini"})


@dataclass(frozen=True)
class RealtimeConfig:
    provider: str = "openai"
    model: str = "gpt-realtime-2"
    api_key_env: str = "OPENAI_API_KEY"
    voice: str = "marin"
    reasoning_effort: str = "low"
    session_max_duration_sec: int = 300
    output_token_cap: int = 800
    request_timeout_sec: float = 10.0


@dataclass(frozen=True)
class AudioConfig:
    capture_sample_rate: int = 24000
    playback_sample_rate: int = 24000
    capture_device: str = "default"
    playback_device: str = "default"


@dataclass(frozen=True)
class ControlConfig:
    socket: Path = field(default_factory=default_control_socket_path)


@dataclass(frozen=True)
class CoordinationConfig:
    shuvoice_status_poll_sec: float = 1.0
    shuvoice_control_timeout_sec: float = 2.0


@dataclass(frozen=True)
class UiConfig:
    show_overlay: bool = False
    overlay_position: str = "top-center"


@dataclass(frozen=True)
class TelemetryConfig:
    sink: str = "stdout"
    file_path: str = ""
    debug_log_raw_text: bool = False


@dataclass(frozen=True)
class PrivacyConfig:
    log_session_audio_duration: bool = True
    log_token_counts: bool = True


@dataclass(frozen=True)
class AppConfig:
    config_version: int = 1
    realtime: RealtimeConfig = field(default_factory=RealtimeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    coordination: CoordinationConfig = field(default_factory=CoordinationConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    def validate(self) -> None:
        if self.realtime.provider not in REALTIME_PROVIDERS:
            allowed = ", ".join(sorted(REALTIME_PROVIDERS))
            raise ValueError(
                f"realtime.provider={self.realtime.provider!r} not in allowlist "
                f"[{allowed}]"
            )
        if (
            self.realtime.provider == "openai"
            and self.realtime.voice not in REALTIME_VOICES
        ):
            allowed = ", ".join(sorted(REALTIME_VOICES))
            raise ValueError(
                f"realtime.voice={self.realtime.voice!r} not in allowlist [{allowed}]"
            )
        if self.realtime.reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("realtime.reasoning_effort must be low, medium, or high")
        if self.realtime.session_max_duration_sec <= 0:
            raise ValueError("realtime.session_max_duration_sec must be greater than 0")
        if self.realtime.output_token_cap <= 0:
            raise ValueError("realtime.output_token_cap must be greater than 0")
        if self.realtime.output_token_cap > 4096:
            raise ValueError("realtime.output_token_cap must be 4096 or less")
        if self.realtime.request_timeout_sec <= 0:
            raise ValueError("realtime.request_timeout_sec must be greater than 0")
        if self.coordination.shuvoice_status_poll_sec <= 0:
            raise ValueError(
                "coordination.shuvoice_status_poll_sec must be greater than 0"
            )
        if self.coordination.shuvoice_control_timeout_sec <= 0:
            raise ValueError(
                "coordination.shuvoice_control_timeout_sec must be greater than 0"
            )
        if self.telemetry.sink not in {"stdout", "file", "maple"}:
            raise ValueError("telemetry.sink must be stdout, file, or maple")


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        config = AppConfig()
        config.validate()
        return config
    data = tomllib.loads(config_path.read_text())
    config = _config_from_mapping(data)
    config.validate()
    return config


def _config_from_mapping(data: dict[str, Any]) -> AppConfig:
    config = AppConfig()
    control_data = dict(data.get("control", {}))
    if control_data.get("socket", "") == "":
        control_data.pop("socket", None)
    elif "socket" in control_data:
        control_data["socket"] = Path(control_data["socket"]).expanduser()

    sections: dict[str, Any] = {
        "realtime": _replace_dataclass(config.realtime, data.get("realtime", {})),
        "audio": _replace_dataclass(config.audio, data.get("audio", {})),
        "control": _replace_dataclass(config.control, control_data),
        "coordination": _replace_dataclass(
            config.coordination, data.get("coordination", {})
        ),
        "ui": _replace_dataclass(config.ui, data.get("ui", {})),
        "telemetry": _replace_dataclass(config.telemetry, data.get("telemetry", {})),
        "privacy": _replace_dataclass(config.privacy, data.get("privacy", {})),
    }
    return replace(config, config_version=data.get("config_version", 1), **sections)


def _replace_dataclass(instance: Any, values: dict[str, Any]) -> Any:
    allowed = {field.name for field in instance.__dataclass_fields__.values()}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")
    return replace(instance, **values)
