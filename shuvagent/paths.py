from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "shuvagent"


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / APP_NAME
    return Path("/tmp") / f"{APP_NAME}-{os.getuid()}"


def data_dir() -> Path:
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / APP_NAME
    )


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def default_local_env_path() -> Path:
    return config_dir() / "local.dev"


def default_control_socket_path() -> Path:
    return runtime_dir() / "control.sock"
