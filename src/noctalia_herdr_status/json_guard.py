"""Validate untrusted JSON values before constructing typed domain records."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast


def loads(contents: str) -> object:
    value: object = json.loads(contents)
    return value


def load(path: Path) -> object:
    return loads(path.read_text(encoding="utf-8"))


def is_record(value: object) -> bool:
    return isinstance(value, dict)


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    entries = cast(Mapping[object, object], value)
    result: dict[str, object] = {}
    for key, item in entries.items():
        if not isinstance(key, str):
            raise ValueError("Expected string object keys")
        result[key] = item
    return result


def array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return list(cast(Sequence[object], value))


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean")
    return value


def integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Expected an integer")
    return value


def strings(value: object) -> list[str]:
    return [text(item) for item in array(value)]
