from pathlib import Path

import pytest

from shuvagent.config import load_config


def test_loads_defaults_when_config_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")

    assert config.realtime.model == "gpt-realtime-2"
    assert config.realtime.voice == "marin"
    assert config.control.socket.name == "control.sock"


def test_example_config_matches_current_schema() -> None:
    config = load_config(Path("examples/config.toml"))

    assert config.realtime.output_token_cap == 800


def test_loads_config_and_expands_socket(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    socket = tmp_path / "agent.sock"
    path.write_text(
        f"""
config_version = 1

[realtime]
voice = "verse"

[control]
socket = "{socket}"
"""
    )

    config = load_config(path)

    assert config.realtime.voice == "verse"
    assert config.control.socket == socket


def test_rejects_non_realtime_voice(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[realtime]
voice = "fable"
"""
    )

    with pytest.raises(ValueError, match="not in allowlist"):
        load_config(path)


def test_rejects_invalid_safety_caps(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[realtime]
session_max_duration_sec = 0
"""
    )

    with pytest.raises(ValueError, match="session_max_duration_sec"):
        load_config(path)

    path.write_text(
        """
[realtime]
output_token_cap = 0
"""
    )

    with pytest.raises(ValueError, match="output_token_cap"):
        load_config(path)

    path.write_text(
        """
[realtime]
output_token_cap = 4097
"""
    )

    with pytest.raises(ValueError, match="4096"):
        load_config(path)
