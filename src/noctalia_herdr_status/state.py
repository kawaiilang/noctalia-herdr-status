"""Pure Herdr snapshot normalization, socket resolution and validation."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import json_guard

AGENT_STATUS_PRIORITY: dict[str, int] = {
    "blocked": 0,
    "working": 1,
    "done": 2,
    "idle": 3,
    "unknown": 4,
}
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._/@:-]+$")
SAFE_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class PaneEntry:
    pane_id: str
    name: str
    agent: str
    status: str
    dir: str
    workspace: str
    tab: str
    focused: bool


@dataclass(frozen=True)
class StatusCounts:
    blocked: int
    working: int
    done: int
    idle: int
    unknown: int
    agents: int
    shells: int
    total: int


@dataclass(frozen=True)
class StatusSnapshot:
    state: str
    running: bool
    counts: StatusCounts
    agents: list[PaneEntry]
    shells: list[PaneEntry]


def offline_snapshot() -> StatusSnapshot:
    return StatusSnapshot(
        state="offline",
        running=False,
        counts=StatusCounts(
            blocked=0,
            working=0,
            done=0,
            idle=0,
            unknown=0,
            agents=0,
            shells=0,
            total=0,
        ),
        agents=[],
        shells=[],
    )


def resolve_herdr_socket(environ: Mapping[str, str], home_dir: Path) -> Path:
    if "HERDR_SOCKET_PATH" in environ:
        return Path(environ["HERDR_SOCKET_PATH"])
    base = Path(environ.get("XDG_CONFIG_HOME", home_dir / ".config"))
    session = environ.get("HERDR_SESSION", "default")
    if session != "default":
        if (
            session in {".", ".."}
            or len(session) > 64
            or not SAFE_SESSION_PATTERN.fullmatch(session)
        ):
            raise ValueError(f"Invalid Herdr session name: {session!r}")
        return base / "herdr" / "sessions" / session / "herdr.sock"
    return base / "herdr" / "herdr.sock"


def sanitize_dir_basename(raw_path: str) -> str:
    stripped = raw_path.strip()
    if stripped.startswith("///"):
        stripped = "/" + stripped.lstrip("/")
    path = PureWindowsPath(stripped)
    return path.name or ("/" if path.root else "")


def validate_pane_id(pane_id: str) -> str:
    if not pane_id or pane_id.startswith("-") or not SAFE_ID_PATTERN.fullmatch(pane_id):
        raise ValueError(f"Invalid pane ID: {pane_id!r}")
    return pane_id


def optional_str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _optional_array(value: object) -> list[object]:
    try:
        return json_guard.array(value)
    except ValueError:
        return []


def _label_map(items: list[object], id_key: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in items:
        if not json_guard.is_record(item):
            continue
        rec = json_guard.record(item)
        item_id = optional_str(rec, id_key)
        if not item_id:
            continue
        label = optional_str(rec, "label")
        if not label:
            number = rec.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                label = str(number)
        labels[item_id] = label
    return labels


def _normalize_agent_status(raw_status: str) -> str:
    if raw_status in AGENT_STATUS_PRIORITY:
        return raw_status
    return "unknown"


def build_snapshot(raw_snapshot: Mapping[str, object] | None) -> StatusSnapshot:
    if raw_snapshot is None:
        return offline_snapshot()

    workspaces = _label_map(
        _optional_array(raw_snapshot.get("workspaces")), "workspace_id"
    )
    tabs = _label_map(_optional_array(raw_snapshot.get("tabs")), "tab_id")

    panes_by_id: dict[str, Mapping[str, object]] = {}
    for item in json_guard.array(raw_snapshot.get("panes")):
        if not json_guard.is_record(item):
            continue
        pane = json_guard.record(item)
        pane_id = optional_str(pane, "pane_id")
        if pane_id:
            panes_by_id[pane_id] = pane

    agents: list[PaneEntry] = []
    agent_pane_ids: set[str] = set()
    counts_by_status = dict.fromkeys(AGENT_STATUS_PRIORITY, 0)

    for item in json_guard.array(raw_snapshot.get("agents")):
        if not json_guard.is_record(item):
            continue
        agent_rec = json_guard.record(item)
        pane_id = optional_str(agent_rec, "pane_id")
        if not pane_id or pane_id in agent_pane_ids:
            continue
        agent_pane_ids.add(pane_id)

        pane_rec = panes_by_id.get(pane_id, {})
        status = _normalize_agent_status(optional_str(agent_rec, "agent_status"))
        agent_name = optional_str(agent_rec, "display_agent") or optional_str(
            agent_rec, "agent"
        )
        display_name = (
            optional_str(agent_rec, "name")
            or agent_name
            or optional_str(pane_rec, "label")
            or pane_id
        )
        raw_cwd = (
            optional_str(agent_rec, "foreground_cwd")
            or optional_str(agent_rec, "cwd")
            or optional_str(pane_rec, "foreground_cwd")
            or optional_str(pane_rec, "cwd")
        )
        workspace_id = optional_str(agent_rec, "workspace_id") or optional_str(
            pane_rec, "workspace_id"
        )
        tab_id = optional_str(agent_rec, "tab_id") or optional_str(pane_rec, "tab_id")

        counts_by_status[status] += 1
        agents.append(
            PaneEntry(
                pane_id=pane_id,
                name=display_name,
                agent=agent_name,
                status=status,
                dir=sanitize_dir_basename(raw_cwd),
                workspace=workspaces.get(workspace_id, ""),
                tab=tabs.get(tab_id, ""),
                focused=bool(agent_rec.get("focused") or pane_rec.get("focused")),
            )
        )

    shells: list[PaneEntry] = []
    for pane_id, pane_rec in panes_by_id.items():
        if pane_id in agent_pane_ids:
            continue
        raw_cwd = optional_str(pane_rec, "foreground_cwd") or optional_str(
            pane_rec, "cwd"
        )
        dir_basename = sanitize_dir_basename(raw_cwd)
        display_name = optional_str(pane_rec, "label") or dir_basename or pane_id
        workspace_id = optional_str(pane_rec, "workspace_id")
        tab_id = optional_str(pane_rec, "tab_id")
        shells.append(
            PaneEntry(
                pane_id=pane_id,
                name=display_name,
                agent="",
                status="shell",
                dir=dir_basename,
                workspace=workspaces.get(workspace_id, ""),
                tab=tabs.get(tab_id, ""),
                focused=bool(pane_rec.get("focused")),
            )
        )

    agents.sort(
        key=lambda entry: (
            AGENT_STATUS_PRIORITY[entry.status],
            entry.name.lower(),
            entry.pane_id,
        )
    )
    shells.sort(
        key=lambda entry: (
            entry.workspace.lower(),
            entry.tab.lower(),
            entry.name.lower(),
            entry.pane_id,
        )
    )

    counts = StatusCounts(
        blocked=counts_by_status["blocked"],
        working=counts_by_status["working"],
        done=counts_by_status["done"],
        idle=counts_by_status["idle"],
        unknown=counts_by_status["unknown"],
        agents=len(agents),
        shells=len(shells),
        total=len(agents) + len(shells),
    )

    summary_state = next(
        (status for status, count in counts_by_status.items() if count),
        "shells" if shells else "empty",
    )

    return StatusSnapshot(
        state=summary_state,
        running=True,
        counts=counts,
        agents=agents,
        shells=shells,
    )
