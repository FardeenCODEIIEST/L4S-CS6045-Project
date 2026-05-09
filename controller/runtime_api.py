"""Small simple_switch_CLI wrapper for register reads and writes."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Iterable


REGISTER_VALUE_RE = re.compile(r"(?:=|\s+)(?P<value>\d+)\s*$")


@dataclass(frozen=True)
class RuntimeAPI:
    thrift_port: int = 9090
    cli_path: str = "simple_switch_CLI"

    def run_cli(self, commands: Iterable[str]) -> str:
        payload = "\n".join(commands) + "\n"
        result = subprocess.run(
            [self.cli_path, "--thrift-port", str(self.thrift_port)],
            input=payload,
            text=True,
            check=True,
            capture_output=True,
        )
        return result.stdout

    def read_register(self, name: str, index: int = 0) -> int:
        output = self.run_cli([f"register_read {name} {index}"])
        return parse_register_value(output)

    def write_register(self, name: str, value: int, index: int = 0) -> None:
        self.run_cli([f"register_write {name} {index} {value}"])


def parse_register_value(output: str) -> int:
    """Parse a simple_switch_CLI register_read value from stdout."""

    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        match = REGISTER_VALUE_RE.search(stripped)
        if match:
            return int(match.group("value"))
    raise ValueError(f"could not parse register value from simple_switch_CLI output: {output!r}")
