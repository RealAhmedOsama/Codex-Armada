from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Console:
    json_mode: bool = False
    quiet: bool = False

    def info(self, message: str) -> None:
        self._emit("info", message)

    def success(self, message: str) -> None:
        self._emit("success", message)

    def warning(self, message: str) -> None:
        self._emit("warning", message, stream=sys.stderr)

    def error(self, message: str) -> None:
        self._emit("error", message, stream=sys.stderr)

    def payload(self, value: Any) -> None:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))

    def table(self, headers: list[str], rows: list[list[Any]]) -> None:
        if self.json_mode:
            self.payload([dict(zip(headers, row, strict=True)) for row in rows])
            return
        widths = [len(str(header)) for header in headers]
        for row in rows:
            for index, value in enumerate(row):
                widths[index] = max(widths[index], len(str(value)))
        print("  ".join(str(header).ljust(widths[index]) for index, header in enumerate(headers)))
        print("  ".join("-" * width for width in widths))
        for row in rows:
            print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))

    def _emit(self, level: str, message: str, *, stream: Any = sys.stdout) -> None:
        if self.quiet and level == "info":
            return
        if self.json_mode:
            print(json.dumps({"level": level, "message": message}, ensure_ascii=False), file=stream)
            return
        icons = {"info": "ℹ", "success": "✓", "warning": "!", "error": "✗"}
        print(f"{icons[level]} {message}", file=stream)
