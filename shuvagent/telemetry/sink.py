from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TextIO

from shuvagent.telemetry.schema import TelemetryEvent


@dataclass
class JsonLineSink:
    stream: TextIO = sys.stdout
    debug_log_raw_text: bool = False

    def emit(self, event: TelemetryEvent) -> None:
        payload = event.to_json_dict(debug_log_raw_text=self.debug_log_raw_text)
        print(json.dumps(payload, sort_keys=True), file=self.stream)
