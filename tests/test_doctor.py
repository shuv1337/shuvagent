import os
from pathlib import Path

from shuvagent.cli import main
from shuvagent.doctor import doctor_exit_code, format_doctor_checks, run_doctor


def test_doctor_fails_without_api_key_but_does_not_print_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[realtime]\noutput_token_cap = 10\n")
    env_path = tmp_path / "missing.env"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    checks = run_doctor(config, env_path=env_path, environ={})
    rendered = format_doctor_checks(checks)

    assert doctor_exit_code(checks) == 1
    assert "openai_api_key" in rendered
    assert "sk-" not in rendered


def test_doctor_loads_local_env_without_rendering_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[realtime]\noutput_token_cap = 10\n")
    env_path = tmp_path / "local.dev"
    env_path.write_text("OPENAI_API_KEY=sk-test-secret\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    checks = run_doctor(config, env_path=env_path, environ={})
    rendered = format_doctor_checks(checks)

    assert any(
        check.name == "openai_api_key" and check.status == "pass" for check in checks
    )
    assert "sk-test-secret" not in rendered
    assert os.environ["OPENAI_API_KEY"] == "sk-test-secret"
    os.environ.pop("OPENAI_API_KEY", None)


def test_doctor_cli_returns_nonzero_for_missing_api_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[realtime]\noutput_token_cap = 10\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))

    code = main(["--config", config.as_posix(), "doctor"])
    out = capsys.readouterr().out

    assert code == 1
    assert "FAIL openai_api_key" in out
    assert "sk-" not in out
