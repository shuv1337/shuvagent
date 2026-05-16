from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from shuvagent.config import AppConfig, load_config
from shuvagent.env_loader import load_env_file
from shuvagent.paths import default_local_env_path


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str

    @property
    def is_failure(self) -> bool:
        return self.status == "fail"


def run_doctor(
    config_path: Path | None = None,
    *,
    env_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[DoctorCheck]:
    env = environ or os.environ
    checks: list[DoctorCheck] = []

    try:
        config = load_config(config_path)
    except Exception as exc:
        return [DoctorCheck("config", "fail", f"invalid config: {exc}")]

    checks.append(DoctorCheck("config", "pass", "config loaded and validated"))
    checks.extend(_safety_cap_checks(config))

    local_env_path = env_path or default_local_env_path()
    loaded = load_env_file(local_env_path)
    if local_env_path.exists():
        checks.append(
            DoctorCheck(
                "local_env",
                "pass",
                f"loaded {loaded} variable(s) from {local_env_path}",
            )
        )
    else:
        checks.append(
            DoctorCheck("local_env", "warn", f"{local_env_path} does not exist")
        )

    api_key = env.get(config.realtime.api_key_env) or os.environ.get(
        config.realtime.api_key_env
    )
    if api_key:
        checks.append(
            DoctorCheck(
                f"{config.realtime.provider}_api_key",
                "pass",
                f"${config.realtime.api_key_env} is set",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                f"{config.realtime.provider}_api_key",
                "fail",
                f"${config.realtime.api_key_env} is not set",
            )
        )

    checks.append(_python_module_check("sounddevice"))
    if config.realtime.provider == "openai":
        checks.append(_python_module_check("websockets"))
    elif config.realtime.provider == "gemini":
        checks.append(_python_module_check("pipecat"))
    checks.extend(
        [
            _command_check("shuvoice", ["shuvoice", "control", "status"]),
            _command_check("wl-paste", ["wl-paste", "--primary", "--no-newline"]),
            _command_check("hyprctl", ["hyprctl", "activewindow", "-j"]),
        ]
    )
    return checks


def format_doctor_checks(checks: list[DoctorCheck]) -> str:
    return "\n".join(
        f"{check.status.upper():4} {check.name}: {check.message}" for check in checks
    )


def doctor_exit_code(checks: list[DoctorCheck]) -> int:
    return 1 if any(check.is_failure for check in checks) else 0


def _safety_cap_checks(config: AppConfig) -> list[DoctorCheck]:
    return [
        DoctorCheck(
            "duration_cap",
            "pass",
            f"session_max_duration_sec={config.realtime.session_max_duration_sec}",
        ),
        DoctorCheck(
            "output_token_cap",
            "pass",
            f"output_token_cap={config.realtime.output_token_cap}",
        ),
    ]


def _python_module_check(module: str) -> DoctorCheck:
    if importlib.util.find_spec(module) is None:
        return DoctorCheck(module, "fail", f"Python module {module!r} is unavailable")
    return DoctorCheck(module, "pass", f"Python module {module!r} is available")


def _command_check(command: str, probe: list[str]) -> DoctorCheck:
    if shutil.which(command) is None:
        return DoctorCheck(command, "warn", f"{command!r} is not on PATH")
    try:
        subprocess.run(
            probe,
            check=True,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except subprocess.TimeoutExpired:
        return DoctorCheck(command, "warn", f"{command!r} probe timed out")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        message = detail[0] if detail else "probe returned nonzero"
        return DoctorCheck(command, "warn", message)
    return DoctorCheck(command, "pass", f"{command!r} probe succeeded")
