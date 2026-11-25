"""Unit tests for pure Herdr snapshot formatting and path/ID validation."""

import json
import unittest
from pathlib import Path

from noctalia_herdr_status import state


class HerdrStateTests(unittest.TestCase):
    def test_resolve_herdr_socket(self) -> None:
        home = Path("/home/tester")
        self.assertEqual(
            state.resolve_herdr_socket({}, home),
            Path("/home/tester/.config/herdr/herdr.sock"),
        )
        self.assertEqual(
            state.resolve_herdr_socket({"XDG_CONFIG_HOME": "/tmp/cfg"}, home),
            Path("/tmp/cfg/herdr/herdr.sock"),
        )
        self.assertEqual(
            state.resolve_herdr_socket(
                {"XDG_CONFIG_HOME": "/tmp/cfg", "HERDR_SESSION": "work"}, home
            ),
            Path("/tmp/cfg/herdr/sessions/work/herdr.sock"),
        )
        self.assertEqual(
            state.resolve_herdr_socket(
                {"HERDR_SOCKET_PATH": "/tmp/custom.sock", "HERDR_SESSION": "work"}, home
            ),
            Path("/tmp/custom.sock"),
        )
        self.assertEqual(
            state.resolve_herdr_socket({"HERDR_SOCKET": "/tmp/ignored"}, home),
            home / ".config/herdr/herdr.sock",
        )
        for bad_session in ("", "..", "../escape", "a/b", " work", "a" * 65):
            with self.assertRaises(ValueError):
                state.resolve_herdr_socket({"HERDR_SESSION": bad_session}, home)

    def test_offline_snapshot(self) -> None:
        snap = state.build_snapshot(None)
        self.assertEqual(snap.state, "offline")
        self.assertFalse(snap.running)
        self.assertEqual(snap.counts.total, 0)

    def test_privacy_normalization_and_sorting(self) -> None:
        raw_snapshot: dict[str, object] = {
            "workspaces": [
                {"workspace_id": "ws1", "number": 1, "label": "infra"},
            ],
            "tabs": [
                {
                    "tab_id": "tab1",
                    "workspace_id": "ws1",
                    "number": 1,
                    "label": "review",
                },
                {"tab_id": "tab2", "workspace_id": "ws1", "number": 2, "label": ""},
            ],
            "panes": [
                {
                    "pane_id": "p1",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": False,
                    "cwd": "/home/tester/secret-parent/nixos",
                    "foreground_cwd": "/home/tester/private/work-repo",
                    "title": "SENSITIVE_TITLE",
                    "terminal_title": "TOP_SECRET_PROMPT_TEXT",
                },
                {
                    "pane_id": "p2",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": True,
                    "cwd": "/home/tester/.config/nixos/",
                    "title": "Allow sudo rm -rf?",
                },
                {
                    "pane_id": "p3",
                    "workspace_id": "ws1",
                    "tab_id": "tab2",
                    "focused": False,
                    "cwd": "/home/tester/projects/alpha",
                    "title": "SECRET_SHELL_CMD",
                },
            ],
            "agents": [
                {
                    "pane_id": "p1",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": False,
                    "agent": "pi",
                    "display_agent": "pi",
                    "name": "builder",
                    "agent_status": "working",
                    "cwd": "/home/tester/secret-parent/nixos",
                    "foreground_cwd": "/home/tester/private/work-repo",
                    "terminal_title": "TOP_SECRET_PROMPT_TEXT",
                    "state_labels": {"blocked": "TOP_SECRET_STATE"},
                },
                {
                    "pane_id": "p2",
                    "workspace_id": "ws1",
                    "tab_id": "tab1",
                    "focused": True,
                    "agent": "codex",
                    "display_agent": "codex",
                    "name": "reviewer",
                    "agent_status": "blocked",
                    "cwd": "/home/tester/.config/nixos/",
                },
            ],
        }
        snap = state.build_snapshot(raw_snapshot)
        self.assertEqual(snap.state, "blocked")
        self.assertTrue(snap.running)
        self.assertEqual(snap.counts.blocked, 1)
        self.assertEqual(snap.counts.working, 1)
        self.assertEqual(snap.counts.agents, 2)
        self.assertEqual(snap.counts.shells, 1)
        self.assertEqual(snap.counts.total, 3)

        self.assertEqual([a.pane_id for a in snap.agents], ["p2", "p1"])
        self.assertEqual(snap.agents[0].name, "reviewer")
        self.assertEqual(snap.agents[0].dir, "nixos")
        self.assertEqual(snap.agents[0].workspace, "infra")
        self.assertEqual(snap.agents[0].tab, "review")
        self.assertTrue(snap.agents[0].focused)
        self.assertEqual(snap.agents[1].dir, "work-repo")

        self.assertEqual(len(snap.shells), 1)
        self.assertEqual(snap.shells[0].pane_id, "p3")
        self.assertEqual(snap.shells[0].name, "alpha")
        self.assertEqual(snap.shells[0].status, "shell")
        self.assertEqual(snap.shells[0].tab, "2")

        serialized = json.dumps(
            {
                "agents": [a.__dict__ for a in snap.agents],
                "shells": [s.__dict__ for s in snap.shells],
            }
        )
        self.assertNotIn("secret-parent", serialized)
        self.assertNotIn("TOP_SECRET_PROMPT_TEXT", serialized)
        self.assertNotIn("TOP_SECRET_STATE", serialized)
        self.assertNotIn("SENSITIVE_TITLE", serialized)
        self.assertNotIn("SECRET_SHELL_CMD", serialized)
        self.assertNotIn("Allow sudo", serialized)

    def test_unknown_agent_status_is_online_and_counted_separately(self) -> None:
        snap = state.build_snapshot(
            {
                "workspaces": [],
                "tabs": [],
                "panes": [{"pane_id": "p1", "cwd": "/tmp/demo"}],
                "agents": [
                    {
                        "pane_id": "p1",
                        "agent": "codex",
                        "agent_status": "unknown",
                        "focused": False,
                    }
                ],
            }
        )
        self.assertTrue(snap.running)
        self.assertEqual(snap.state, "unknown")
        self.assertEqual(snap.counts.idle, 0)
        self.assertEqual(snap.counts.unknown, 1)
        self.assertEqual(snap.agents[0].status, "unknown")
        self.assertEqual(snap.agents[0].name, "codex")

    def test_required_arrays_distinguish_empty_from_unreadable(self) -> None:
        snap = state.build_snapshot({"panes": [], "agents": []})
        self.assertTrue(snap.running)
        self.assertEqual(snap.state, "empty")
        for key in ("panes", "agents"):
            raw: dict[str, object] = {"panes": [], "agents": []}
            del raw[key]
            with self.assertRaises(ValueError):
                state.build_snapshot(raw)
            for invalid in (None, {"invalid": True}, "[]"):
                raw[key] = invalid
                with self.assertRaises(ValueError):
                    state.build_snapshot(raw)

    def test_sanitize_dir_basename(self) -> None:
        self.assertEqual(state.sanitize_dir_basename(""), "")
        self.assertEqual(state.sanitize_dir_basename("/"), "/")
        self.assertEqual(state.sanitize_dir_basename("///"), "/")
        self.assertEqual(
            state.sanitize_dir_basename("/home/tester/.config/nixos/"),
            "nixos",
        )
        self.assertEqual(
            state.sanitize_dir_basename(r"C:\Users\private\project"),
            "project",
        )
        self.assertEqual(state.sanitize_dir_basename(r"\\server\private"), "/")

    def test_validate_pane_id(self) -> None:
        self.assertEqual(state.validate_pane_id("pane-1/a:b"), "pane-1/a:b")
        for bad_id in ("", "--evil", "p1;rm -rf", "pane with space"):
            with self.assertRaises(ValueError):
                state.validate_pane_id(bad_id)


if __name__ == "__main__":
    unittest.main()
