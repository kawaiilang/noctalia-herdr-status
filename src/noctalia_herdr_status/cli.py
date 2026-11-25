"""Query Herdr TUI session metadata and focus terminal panes for Noctalia."""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from . import json_guard
from .compositor import UmbrielBackend, WindowBackend
from .state import (
    StatusSnapshot,
    build_snapshot,
    optional_str,
    resolve_herdr_socket,
    validate_pane_id,
)

MAX_RPC_BYTES = 4 * 1024 * 1024
STATUS_BUDGET_SECONDS = 2.1  # The service allows 2.5s including startup and output.
FOCUS_TIMEOUT_SECONDS = 3.0


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Herdr request timed out")
    return seconds


def rpc_request(
    socket_path: Path,
    method: str,
    params: Mapping[str, object],
    timeout: float = STATUS_BUDGET_SECONDS,
) -> Mapping[str, object] | None:
    request = (
        json.dumps(
            {
                "id": "noctalia-herdr-status",
                "method": method,
                "params": dict(params),
            }
        )
        + "\n"
    ).encode("utf-8")
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        try:
            conn.connect(str(socket_path))
        except (FileNotFoundError, ConnectionRefusedError):
            return None
        conn.settimeout(remaining(deadline))
        conn.sendall(request)
        chunks = bytearray()
        while True:
            conn.settimeout(remaining(deadline))
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_RPC_BYTES:
                raise ValueError("Herdr response exceeded size limit")
            if b"\n" in chunk:
                break

    line = bytes(chunks).split(b"\n", 1)[0].decode("utf-8", errors="strict").strip()
    if not line:
        raise ValueError("Empty response from Herdr")
    payload = json_guard.record(json_guard.loads(line))
    if "error" in payload and payload["error"] is not None:
        raise ValueError("Herdr returned an RPC error")
    return json_guard.record(payload.get("result"))


def query_session_snapshot(
    socket_path: Path, timeout: float = STATUS_BUDGET_SECONDS
) -> Mapping[str, object] | None:
    result = rpc_request(socket_path, "session.snapshot", {}, timeout)
    if result is None:
        return None
    result_type = optional_str(result, "type")
    if result_type and result_type != "session_snapshot":
        raise ValueError(f"Unexpected Herdr response type: {result_type!r}")
    return json_guard.record(result.get("snapshot"))


def run_command(argv: list[str], timeout: float) -> str:
    return subprocess.run(
        argv, capture_output=True, text=True, input="", timeout=timeout, check=True
    ).stdout


_TITLE_SEPARATORS = re.compile(r"\s*(?:・|·)\s*|\s+(?:-|—|\|)\s+")


def _matches_window_app_id(win: Mapping[str, object], override: str) -> bool:
    if not override:
        return True
    return optional_str(win, "app_id") == override


def _window_title_segments(win: Mapping[str, object]) -> tuple[str, ...]:
    title = optional_str(win, "title")
    if not title:
        return ()
    return tuple(
        segment.strip().lower()
        for segment in _TITLE_SEPARATORS.split(title)
        if segment.strip()
    )


def _window_id(win: Mapping[str, object]) -> str:
    win_id = win.get("id")
    if not isinstance(win_id, str) or not win_id:
        raise ValueError("Invalid window ID in compositor response")
    return win_id


def _endpoint_pids(row: Mapping[str, object]) -> set[int]:
    # lsfd encodes each ENDPOINTS element as "pid,command,fd/mode".
    return {
        int(endpoint.partition(",")[0])
        for endpoint in json_guard.strings(row.get("endpoints"))
    }


def _proc_stat(pid: int) -> list[bytes]:
    # Skip comm, which can itself contain spaces and ')'.
    stat = (Path("/proc") / str(pid) / "stat").read_bytes()
    return stat.rsplit(b")", 1)[1].split()


def attached_terminal_hosts(socket_path: Path, lsfd: str, deadline: float) -> set[int]:
    # Follow the server's TUI socket to its clients, then each foreground
    # client's terminal to the process holding the other end of its PTY.
    output = run_command(
        [
            lsfd,
            "--json",
            "--output",
            "PID,FD,CHRDRV,UNIX.PATH,SOCK.LISTENING,ENDPOINTS",
            "--filter",
            'COMMAND == "herdr" && (UNIX.PATH || (FD == 0 && CHRDRV == "pts"))',
        ],
        remaining(deadline),
    )
    rows = [
        json_guard.record(row)
        for row in json_guard.array(
            json_guard.record(json_guard.loads(output)).get("lsfd")
        )
    ]
    api_servers = {
        json_guard.integer(row.get("pid"))
        for row in rows
        if row.get("unix.path") == str(socket_path)
        and row.get("sock.listening") is True
    }
    if len(api_servers) != 1:
        return set()
    client_socket = socket_path.with_name(socket_path.stem + "-client.sock")
    if (
        "HERDR_SOCKET_PATH" not in os.environ
        and "HERDR_CLIENT_SOCKET_PATH" in os.environ
    ):
        client_socket = Path(os.environ["HERDR_CLIENT_SOCKET_PATH"])
    clients: set[int] = set()
    for row in rows:
        if (
            row.get("pid") in api_servers
            and row.get("unix.path") == str(client_socket)
            and row.get("sock.listening") is False
        ):
            clients.update(_endpoint_pids(row))

    hosts: set[int] = set()
    for row in rows:
        pid = json_guard.integer(row.get("pid"))
        if pid not in clients or row.get("fd") != 0 or row.get("chrdrv") != "pts":
            continue
        try:
            _, _, pgrp, _, tty, tpgid = _proc_stat(pid)[:6]
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if tty != b"0" and pgrp == tpgid:
            hosts.update(_endpoint_pids(row))
    return hosts


def terminal_window_pid(host: int, window_pids: set[int]) -> int | None:
    # The PTY host is either the terminal window process itself or a child
    # running the same executable. A different terminal launched from another
    # window owns its own PTY and will not match an unrelated ancestor.
    host_exe = Path("/proc") / str(host) / "exe"
    pid = host
    try:
        while pid > 1:
            if pid in window_pids:
                return (
                    pid if host_exe.samefile(Path("/proc") / str(pid) / "exe") else None
                )
            pid = int(_proc_stat(pid)[1])
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return None


def _select_by_title(
    matches: list[Mapping[str, object]],
    title_pairs: tuple[tuple[str, str], ...],
    hints: tuple[str, ...],
) -> str | None:
    for first, second in title_pairs:
        left = first.strip().lower()
        right = second.strip().lower()
        if not left or not right:
            continue
        by_pair = [
            win
            for win in matches
            if (segments := _window_title_segments(win))
            and left in segments
            and right in segments
        ]
        if len(by_pair) == 1:
            return _window_id(by_pair[0])

    for hint in hints:
        needle = hint.strip().lower()
        if not needle or needle == "/":
            continue
        by_title = [win for win in matches if needle in _window_title_segments(win)]
        if len(by_title) == 1:
            return _window_id(by_title[0])

    return None


def terminal_window_id(
    backend: WindowBackend,
    deadline: float,
    hosts: set[int],
    title_pairs: tuple[tuple[str, str], ...] = (),
    shared_hints: tuple[str, ...] = (),
    hints: tuple[str, ...] = (),
) -> str:
    windows = backend.list_windows(remaining(deadline))
    window_counts = Counter(
        pid for win in windows if type(pid := win.get("pid")) is int
    )
    window_pids = set(window_counts)
    owners = {terminal_window_pid(host, window_pids) for host in hosts}
    override = os.environ.get("HERDR_WINDOW_APP_ID", "").strip()
    matches: list[Mapping[str, object]] = [
        win
        for win in windows
        if type(pid := win.get("pid")) is int
        and pid in owners
        and _matches_window_app_id(win, override)
    ]
    if not matches:
        raise ValueError("Could not identify a window hosting this Herdr client")
    if len(matches) == 1:
        return _window_id(matches[0])

    unique_pid_matches = [
        win
        for win in matches
        if type(pid := win.get("pid")) is int and window_counts[pid] == 1
    ]
    all_unique = len(unique_pid_matches) == len(matches)
    selected = _select_by_title(
        matches,
        title_pairs,
        hints if all_unique else shared_hints,
    )
    if selected is not None:
        return selected

    if unique_pid_matches:
        focused = backend.focused_window(remaining(deadline))
        if focused is not None:
            focused_id = _window_id(focused)
            if any(_window_id(win) == focused_id for win in unique_pid_matches):
                return focused_id

    raise ValueError("Could not uniquely identify a terminal window hosting Herdr")


def status_snapshot(socket_path: Path) -> StatusSnapshot:
    raw_snapshot = query_session_snapshot(socket_path, STATUS_BUDGET_SECONDS)
    return build_snapshot(raw_snapshot)


def make_umbriel_backend(umbriel: str) -> UmbrielBackend:
    return UmbrielBackend(umbriel, run_command)


def focus_pane(
    socket_path: Path,
    umbriel: str,
    pane_id: str,
    lsfd: str = "lsfd",
    backend: WindowBackend | None = None,
) -> None:
    validated = validate_pane_id(pane_id)
    deadline = time.monotonic() + FOCUS_TIMEOUT_SECONDS
    raw_snapshot = query_session_snapshot(socket_path, remaining(deadline))
    if raw_snapshot is None:
        raise ValueError("Herdr server is not running")
    snapshot = build_snapshot(raw_snapshot)
    entries = (*snapshot.agents, *snapshot.shells)
    target = next((entry for entry in entries if entry.pane_id == validated), None)
    if target is None:
        raise ValueError(f"Pane not found in Herdr session: {validated}")

    focused_entry = next((entry for entry in entries if entry.focused), None)
    if focused_entry is not None:
        title_pairs = ((focused_entry.workspace, focused_entry.tab),)
        shared_hints = (focused_entry.workspace, "herdr")
        hints = (
            focused_entry.workspace,
            target.workspace,
            target.dir,
            "herdr",
        )
    else:
        title_pairs = ((target.workspace, target.tab),)
        shared_hints = ("herdr", target.workspace)
        hints = (target.workspace, target.dir, "herdr")

    active_backend: WindowBackend = (
        backend if backend is not None else make_umbriel_backend(umbriel)
    )
    hosts = attached_terminal_hosts(socket_path, lsfd, deadline)
    window_id = terminal_window_id(
        active_backend,
        deadline,
        hosts,
        title_pairs=title_pairs,
        shared_hints=shared_hints,
        hints=hints,
    )
    result = rpc_request(
        socket_path, "pane.focus", {"pane_id": validated}, remaining(deadline)
    )
    if result is None:
        raise ValueError("Herdr server stopped while focusing pane")
    active_backend.focus_window(window_id, remaining(deadline))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--umbriel", default="umbriel")
    parser.add_argument("--lsfd", default="lsfd")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    focus_parser = subparsers.add_parser("focus")
    focus_parser.add_argument("pane_id")

    arguments = parser.parse_args(argv)
    umbriel = str(arguments.umbriel)
    command = str(arguments.command)

    try:
        socket_path = resolve_herdr_socket(os.environ, Path.home())
        if command == "status":
            snapshot = status_snapshot(socket_path)
            print(json.dumps(asdict(snapshot)))
            return 0
        if command == "focus":
            focus_pane(
                socket_path, umbriel, str(arguments.pane_id), str(arguments.lsfd)
            )
            return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
