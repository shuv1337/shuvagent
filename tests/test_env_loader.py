from pathlib import Path

from shuvagent.env_loader import load_env_file


def test_load_env_file_supports_exports_and_preserves_existing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "local.dev"
    path.write_text(
        """
# comment
OPENAI_API_KEY=sk-from-file
export OTHER_KEY="value"
"""
    )
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")

    loaded = load_env_file(path)

    assert loaded == 1
    assert OTHER_KEY_ENV() == "value"
    assert OPENAI_KEY_ENV() == "already-set"


def test_load_env_file_can_override(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "local.dev"
    path.write_text("OPENAI_API_KEY=sk-from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")

    assert load_env_file(path, override=True) == 1
    assert OPENAI_KEY_ENV() == "sk-from-file"


def OPENAI_KEY_ENV() -> str:
    import os

    return os.environ["OPENAI_API_KEY"]


def OTHER_KEY_ENV() -> str:
    import os

    return os.environ["OTHER_KEY"]
