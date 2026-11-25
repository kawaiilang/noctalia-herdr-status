"""Compositor window-lookup and focus backends (currently Umbriel)."""

from collections.abc import Callable, Mapping
from typing import Protocol

from . import json_guard

CommandRunner = Callable[[list[str], float], str]


class WindowBackend(Protocol):
    def list_windows(self, timeout: float) -> list[Mapping[str, object]]: ...

    def focused_window(self, timeout: float) -> Mapping[str, object] | None: ...

    def focus_window(self, window_id: str, timeout: float) -> None: ...


class UmbrielBackend:
    """Window inspection and focus backend for the Umbriel Wayland compositor."""

    def __init__(self, binary: str, runner: CommandRunner) -> None:
        self._binary = binary
        self._runner = runner

    def list_windows(self, timeout: float) -> list[Mapping[str, object]]:
        raw = self._runner([self._binary, "windows", "--json"], timeout)
        return [
            json_guard.record(item)
            for item in json_guard.array(json_guard.loads(raw))
        ]

    def focused_window(self, timeout: float) -> Mapping[str, object] | None:
        raw = self._runner([self._binary, "focused-window", "--json"], timeout)
        focused = json_guard.loads(raw)
        if json_guard.is_record(focused):
            return json_guard.record(focused)
        return None

    def focus_window(self, window_id: str, timeout: float) -> None:
        self._runner([self._binary, "msg", "window-focus", window_id], timeout)
