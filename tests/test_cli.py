"""Unit tests for noctalia_herdr_status.cli and compositor backend."""

import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from noctalia_herdr_status import cli, json_guard


def _start_mock_herdr_server(
    socket_path: Path, responses: list[dict[str, object]]
) -> tuple[socket.socket, threading.Thread, list[Mapping[str, object]]]:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(len(responses))
    requests: list[Mapping[str, object]] = []

    def serve() -> None:
        try:
            for payload in responses:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2.0)
                    buf = bytearray()
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf.extend(chunk)
                    line = bytes(buf).split(b"\n", 1)[0].decode("utf-8")
                    parsed = json_guard.loads(line)
                    if json_guard.is_record(parsed):
                        requests.append(json_guard.record(parsed))
                    reply = (json.dumps(payload) + "\n").encode("utf-8")
                    conn.sendall(reply)
        except OSError:
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server, thread, requests


class HerdrStatusTests(unittest.TestCase):
    def test_offline_when_socket_missing_or_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.sock"
            self.assertIsNone(cli.query_session_snapshot(missing))

            stale = Path(tmp) / "stale.sock"
            stale.write_text("", encoding="utf-8")
            self.assertIsNone(cli.query_session_snapshot(stale))

            snap = cli.status_snapshot(missing)
            self.assertEqual(snap.state, "offline")
            self.assertFalse(snap.running)
            self.assertEqual(snap.counts.total, 0)

    def test_query_snapshot_over_unix_socket(self) -> None:
        raw_snapshot: dict[str, object] = {
            "version": "0.9.5",
            "protocol": 22,
            "workspaces": [{"workspace_id": "ws1", "number": 1, "label": "infra"}],
            "tabs": [{"tab_id": "tab1", "workspace_id": "ws1", "label": "review"}],
            "panes": [
                {
                    "pane_id": "p1",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": True,
                    "cwd": "/home/tester/.config/nixos/",
                },
                {
                    "pane_id": "p2",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": False,
                    "cwd": "/home/tester/projects/alpha",
                },
            ],
            "agents": [
                {
                    "pane_id": "p1",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": True,
                    "agent": "codex",
                    "display_agent": "codex",
                    "name": "reviewer",
                    "agent_status": "blocked",
                    "cwd": "/home/tester/.config/nixos/",
                }
            ],
            "layouts": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "herdr.sock"
            server, thread, requests = _start_mock_herdr_server(
                sock,
                [
                    {
                        "id": "noctalia-herdr-status",
                        "result": {
                            "type": "session_snapshot",
                            "snapshot": raw_snapshot,
                        },
                    }
                ],
            )
            try:
                snap = cli.status_snapshot(sock)
            finally:
                server.close()
                thread.join(timeout=2.0)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get("method"), "session.snapshot")
        self.assertEqual(snap.state, "blocked")
        self.assertTrue(snap.running)
        self.assertEqual(snap.counts.blocked, 1)
        self.assertEqual(snap.counts.agents, 1)
        self.assertEqual(snap.counts.shells, 1)
        self.assertEqual(snap.counts.total, 2)
        self.assertEqual([a.pane_id for a in snap.agents], ["p1"])
        self.assertEqual([s.pane_id for s in snap.shells], ["p2"])

    def test_connected_read_errors_propagate_as_unknown(self) -> None:
        for error in (TimeoutError(), ConnectionResetError()):
            with mock.patch("noctalia_herdr_status.cli.socket.socket") as sock:
                conn = sock.return_value.__enter__.return_value
                conn.recv.side_effect = error
                with self.assertRaises(type(error)):
                    cli.query_session_snapshot(Path("/herdr.sock"))
                conn.connect.assert_called_once()

    def test_focus_sends_pane_focus_and_raises_terminal_window(self) -> None:
        snapshot_reply: dict[str, object] = {
            "id": "noctalia-herdr-status",
            "result": {
                "type": "session_snapshot",
                "snapshot": {
                    "workspaces": [{"workspace_id": "ws1", "label": "infra"}],
                    "tabs": [{"tab_id": "tab1", "label": "review"}],
                    "panes": [
                        {
                            "pane_id": "p2",
                            "workspace_id": "ws1",
                            "tab_id": "tab1",
                            "cwd": "/home/tester/.config/nixos",
                            "focused": True,
                        }
                    ],
                    "agents": [],
                },
            },
        }
        focus_reply: dict[str, object] = {
            "id": "noctalia-herdr-status",
            "result": {"type": "pane_info", "pane": {"pane_id": "p2"}},
        }
        windows = [
            {
                "app_id": "code",
                "pid": 40,
                "id": "w0",
                "title": "bar.nix - nixos - Visual Studio Code",
            },
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 41,
                "id": "w1",
                "title": "other ・ shell",
            },
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 42,
                "id": "w2",
                "title": "infra ・ review",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "herdr.sock"
            server, thread, requests = _start_mock_herdr_server(
                sock, [snapshot_reply, focus_reply]
            )
            try:
                with (
                    mock.patch(
                        "noctalia_herdr_status.cli.attached_terminal_hosts",
                        return_value={101, 102},
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.terminal_window_pid",
                        side_effect=[41, 42],
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.run_command",
                        side_effect=[json.dumps(windows), ""],
                    ) as run,
                ):
                    cli.focus_pane(sock, "umbriel", "p2")
            finally:
                server.close()
                thread.join(timeout=2.0)

        self.assertEqual(
            [req.get("method") for req in requests], ["session.snapshot", "pane.focus"]
        )
        self.assertEqual(requests[1].get("params"), {"pane_id": "p2"})
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["umbriel", "windows", "--json"],
                ["umbriel", "msg", "window-focus", "w2"],
            ],
        )

    def test_focus_disambiguates_shared_pid_ghostty_windows(self) -> None:
        snapshot_reply: dict[str, object] = {
            "id": "noctalia-herdr-status",
            "result": {
                "type": "session_snapshot",
                "snapshot": {
                    "workspaces": [
                        {"workspace_id": "ws1", "label": "infra"},
                        {"workspace_id": "ws2", "label": "other"},
                    ],
                    "tabs": [
                        {"tab_id": "tab1", "label": "review"},
                        {"tab_id": "tab2", "label": "deploy"},
                    ],
                    "panes": [
                        {
                            "pane_id": "p1",
                            "workspace_id": "ws1",
                            "tab_id": "tab1",
                            "cwd": "/home/tester/.config/nixos",
                            "focused": True,
                        },
                        {
                            "pane_id": "p2",
                            "workspace_id": "ws2",
                            "tab_id": "tab2",
                            "cwd": "/home/tester/other",
                            "focused": False,
                        },
                    ],
                    "agents": [],
                },
            },
        }
        focus_reply: dict[str, object] = {
            "id": "noctalia-herdr-status",
            "result": {"type": "pane_info", "pane": {"pane_id": "p2"}},
        }
        shared_windows = [
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 50,
                "id": "gt-shell",
                "title": "other",
            },
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 50,
                "id": "gt-herdr",
                "title": "infra ・ review",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "herdr.sock"
            server, thread, requests = _start_mock_herdr_server(
                sock, [snapshot_reply, focus_reply]
            )
            try:
                with (
                    mock.patch(
                        "noctalia_herdr_status.cli.attached_terminal_hosts",
                        return_value={50},
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.terminal_window_pid",
                        return_value=50,
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.run_command",
                        side_effect=[json.dumps(shared_windows), ""],
                    ) as run,
                ):
                    cli.focus_pane(sock, "umbriel", "p2")
            finally:
                server.close()
                thread.join(timeout=2.0)

        self.assertEqual(
            [req.get("method") for req in requests], ["session.snapshot", "pane.focus"]
        )
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["umbriel", "windows", "--json"],
                ["umbriel", "msg", "window-focus", "gt-herdr"],
            ],
        )

    def test_focus_respects_window_app_id_override(self) -> None:
        windows = [
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 41,
                "id": "w1",
                "title": "ghostty",
            },
            {
                "app_id": "foot",
                "pid": 42,
                "id": "w2",
                "title": "foot",
            },
        ]
        with (
            mock.patch.dict(os.environ, {"HERDR_WINDOW_APP_ID": "foot"}),
            mock.patch(
                "noctalia_herdr_status.cli.terminal_window_pid", side_effect=[41, 42]
            ),
            mock.patch(
                "noctalia_herdr_status.cli.run_command",
                return_value=json.dumps(windows),
            ),
        ):
            backend = cli.make_umbriel_backend("umbriel")
            self.assertEqual(
                cli.terminal_window_id(backend, 1e12, {101, 102}),
                "w2",
            )

    def test_terminal_must_belong_to_the_window_process(self) -> None:
        with (
            mock.patch.object(
                Path, "read_bytes", return_value=b"50 (pty) host) S 51 50 50 0 -1"
            ),
            mock.patch.object(Path, "samefile", return_value=True),
        ):
            self.assertEqual(cli.terminal_window_pid(50, {51}), 51)
        with (
            mock.patch.object(
                Path, "read_bytes", return_value=b"50 (external) S 51 50 50 0 -1"
            ),
            mock.patch.object(Path, "samefile", return_value=False),
        ):
            self.assertIsNone(cli.terminal_window_pid(50, {51}))

    def test_focus_falls_back_to_focused_terminal_window_when_titles_match_none(
        self,
    ) -> None:
        windows = [
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 41,
                "id": "w1",
                "title": "ghostty",
                "focused": True,
            },
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 42,
                "id": "w2",
                "title": "ghostty",
                "focused": True,
            },
        ]
        for selected in ({"id": "w2"}, {"id": "unrelated"}, None):
            with (
                mock.patch(
                    "noctalia_herdr_status.cli.terminal_window_pid",
                    side_effect=[41, 42],
                ),
                mock.patch(
                    "noctalia_herdr_status.cli.run_command",
                    side_effect=[json.dumps(windows), json.dumps(selected)],
                ) as run,
            ):
                backend = cli.make_umbriel_backend("umbriel")
                if selected == {"id": "w2"}:
                    self.assertEqual(
                        cli.terminal_window_id(backend, 1e12, {101, 102}),
                        "w2",
                    )
                else:
                    with self.assertRaises(ValueError):
                        cli.terminal_window_id(backend, 1e12, {101, 102})
                self.assertEqual(
                    run.call_args_list[-1].args[0],
                    ["umbriel", "focused-window", "--json"],
                )

    def test_only_clients_of_the_requested_server_and_tui_socket_match(self) -> None:
        def sock(pid: int, name: str, *endpoints: str) -> dict[str, object]:
            return {
                "pid": pid,
                "unix.path": name,
                "endpoints": list(endpoints),
                "sock.listening": not endpoints,
            }

        def tty(pid: int, host: int) -> dict[str, object]:
            return {
                "pid": pid,
                "fd": 0,
                "chrdrv": "pts",
                "endpoints": [f"{host},ghostty,35rw"],
            }

        rows = [
            sock(11, "/tmp/session.sock"),
            sock(11, "/tmp/session-client.sock", "101,herdr,4rw", "104,herdr,4rw"),
            sock(11, "/tmp/session.sock", "102,herdr,4rw"),
            sock(12, "/tmp/other-client.sock", "103,herdr,4rw"),
            tty(101, 51),
            tty(102, 52),
            tty(103, 53),
            tty(104, 54),
        ]
        with (
            mock.patch.dict(os.environ, {"HERDR_SOCKET_PATH": "/tmp/session.sock"}),
            mock.patch(
                "noctalia_herdr_status.cli.run_command",
                return_value=json.dumps({"lsfd": rows}),
            ),
            mock.patch.object(
                Path,
                "read_bytes",
                side_effect=[
                    b"101 (herdr) S 99 101 99 34816 101",
                    b"104 (herdr) S 99 104 99 34817 99",
                ],
            ),
        ):
            self.assertEqual(
                cli.attached_terminal_hosts(Path("/tmp/session.sock"), "lsfd", 1e12),
                {51},
            )

    def test_focus_fails_without_raising_window(self) -> None:
        for pane_id in ("--evil", "p1;rm -rf"):
            with self.assertRaises(ValueError):
                cli.focus_pane(Path("/missing.sock"), "umbriel", pane_id)

        snapshot_reply: dict[str, object] = {
            "id": "noctalia-herdr-status",
            "result": {
                "type": "session_snapshot",
                "snapshot": {
                    "workspaces": [],
                    "tabs": [],
                    "panes": [{"pane_id": "p1", "cwd": "/tmp/demo"}],
                    "agents": [],
                },
            },
        }
        unrelated = {
            "app_id": "com.mitchellh.ghostty",
            "pid": 51,
            "id": "w1",
            "title": "demo",
        }

        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "herdr.sock"
            server, thread, requests = _start_mock_herdr_server(sock, [snapshot_reply])
            try:
                with (
                    mock.patch.dict("os.environ", {"HERDR_SOCKET_PATH": str(sock)}),
                    mock.patch("noctalia_herdr_status.cli.run_command") as run,
                    mock.patch("sys.stderr"),
                ):
                    self.assertEqual(
                        cli.main(["--umbriel", "umbriel", "focus", "missing"]),
                        1,
                    )
                    run.assert_not_called()
            finally:
                server.close()
                thread.join(timeout=2.0)
            self.assertEqual([r.get("method") for r in requests], ["session.snapshot"])

        shared_pid_windows = [
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 50,
                "id": "w2",
                "title": "ghostty",
            },
            {
                "app_id": "com.mitchellh.ghostty",
                "pid": 50,
                "id": "w3",
                "title": "demo",
            },
        ]
        for windows in ([], [unrelated], shared_pid_windows):
            with tempfile.TemporaryDirectory() as tmp:
                sock = Path(tmp) / "herdr.sock"
                server, thread, requests = _start_mock_herdr_server(
                    sock, [snapshot_reply]
                )
                try:
                    with (
                        mock.patch.dict("os.environ", {"HERDR_SOCKET_PATH": str(sock)}),
                        mock.patch(
                            "noctalia_herdr_status.cli.attached_terminal_hosts",
                            return_value={101},
                        ),
                        mock.patch(
                            "noctalia_herdr_status.cli.terminal_window_pid",
                            return_value=50,
                        ),
                        mock.patch(
                            "noctalia_herdr_status.cli.run_command",
                            return_value=json.dumps(windows),
                        ) as run,
                        mock.patch("sys.stderr"),
                    ):
                        self.assertEqual(
                            cli.main(["--umbriel", "umbriel", "focus", "p1"]),
                            1,
                        )
                        self.assertFalse(
                            any(
                                call.args[0][:2] == ["umbriel", "msg"]
                                for call in run.call_args_list
                            )
                        )
                finally:
                    server.close()
                    thread.join(timeout=2.0)
                self.assertEqual(
                    [r.get("method") for r in requests], ["session.snapshot"]
                )

        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "herdr.sock"
            server, thread, requests = _start_mock_herdr_server(
                sock,
                [
                    snapshot_reply,
                    {"id": "noctalia-herdr-status", "error": {"code": "not_found"}},
                ],
            )
            try:
                with (
                    mock.patch.dict("os.environ", {"HERDR_SOCKET_PATH": str(sock)}),
                    mock.patch(
                        "noctalia_herdr_status.cli.attached_terminal_hosts",
                        return_value={101},
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.terminal_window_pid",
                        return_value=51,
                    ),
                    mock.patch(
                        "noctalia_herdr_status.cli.run_command",
                        return_value=json.dumps([unrelated]),
                    ) as run,
                    mock.patch("sys.stderr"),
                ):
                    self.assertEqual(
                        cli.main(["--umbriel", "umbriel", "focus", "p1"]), 1
                    )
                    self.assertFalse(
                        any(
                            call.args[0][:2] == ["umbriel", "msg"]
                            for call in run.call_args_list
                        )
                    )
            finally:
                server.close()
                thread.join(timeout=2.0)
        self.assertEqual(
            [r.get("method") for r in requests], ["session.snapshot", "pane.focus"]
        )

    def test_packaged_helper_imports_and_reports_status(self) -> None:
        helper = os.environ.get("HERDR_STATUS_HELPER")
        if not helper:
            self.skipTest("HERDR_STATUS_HELPER is not set")
        clean_env = {
            key: value for key, value in os.environ.items() if key != "PYTHONPATH"
        }
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.sock"
            offline = subprocess.run(
                [helper, "status"],
                env={**clean_env, "HERDR_SOCKET_PATH": str(missing)},
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(offline.returncode, 0, offline.stderr)
            offline_payload = json_guard.record(json_guard.loads(offline.stdout))
            self.assertEqual(offline_payload["state"], "offline")
            self.assertEqual(offline_payload["running"], False)

            sock = Path(tmp) / "herdr.sock"
            server, thread, _requests = _start_mock_herdr_server(
                sock,
                [
                    {
                        "id": "noctalia-herdr-status",
                        "result": {
                            "type": "session_snapshot",
                            "snapshot": {
                                "workspaces": [],
                                "tabs": [],
                                "panes": [{"pane_id": "p1", "cwd": "/tmp/demo"}],
                                "agents": [
                                    {
                                        "pane_id": "p1",
                                        "agent": "codex",
                                        "agent_status": "working",
                                        "focused": True,
                                    }
                                ],
                            },
                        },
                    }
                ],
            )
            try:
                online = subprocess.run(
                    [helper, "status"],
                    env={**clean_env, "HERDR_SOCKET_PATH": str(sock)},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            finally:
                server.close()
                thread.join(timeout=2.0)
            self.assertEqual(online.returncode, 0, online.stderr)
            online_payload = json_guard.record(json_guard.loads(online.stdout))
            self.assertEqual(online_payload["state"], "working")
            self.assertEqual(online_payload["running"], True)


if __name__ == "__main__":
    unittest.main()
