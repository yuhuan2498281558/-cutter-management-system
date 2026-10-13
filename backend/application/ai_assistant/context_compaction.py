"""Lossless structural compaction for model-visible tool results only.

This module does not summarize, aggregate, filter, or mutate tool evidence.
The original tool result remains suitable for reporting and persistence.
"""

import copy
import json
import math
from decimal import Decimal
from typing import Callable


COLUMNAR_FORMAT = "ai-assistant-columnar-v1"
COLUMNAR_INSTRUCTIONS = (
    "Lossless JSON: data contains the original result. At each table_paths path, "
    "columns lists field names and rows lists values in that order. Each row is "
    "one original object; null stays unknown, never zero. Other fields are unchanged."
)
_ENVELOPE_KEYS = {"format", "instructions", "table_paths", "data"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


def _exact_float(value):
    parsed = float(value)
    # Tool JSON normally comes from Python floats. Preserve arbitrary callers'
    # higher-precision/underflowing literals by declining to encode them.
    if not math.isfinite(parsed) or Decimal(str(parsed)) != Decimal(value):
        raise ValueError("JSON float would lose decimal precision")
    return parsed


def _parse_json(content):
    return json.loads(
        content, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        parse_float=_exact_float,
    )


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _is_error_result(value):
    """Keep errors intact, including failures nested inside a result wrapper."""
    if isinstance(value, dict):
        if value.get("error") or value.get("success") is False:
            return True
        if value.get("status") in ("error", "failed", "failure"):
            return True
        return any(_is_error_result(child) for child in value.values())
    if isinstance(value, list):
        return any(_is_error_result(child) for child in value)
    return False


def _pack_columnar(original):
    paths = []

    def visit(node, path):
        if isinstance(node, list) and len(node) >= 3:
            if all(isinstance(row, dict) for row in node) and node[0]:
                columns = list(node[0])
                if all(
                    row.keys() == node[0].keys()
                    and all(not isinstance(value, (dict, list)) for value in row.values())
                    for row in node
                ):
                    paths.append(path)
                    return {
                        "columns": columns,
                        "rows": [[row[column] for column in columns] for row in node],
                    }
        if isinstance(node, dict):
            return {key: visit(value, path + [key]) for key, value in node.items()}
        if isinstance(node, list):
            return [visit(value, path + [index]) for index, value in enumerate(node)]
        return node

    data = visit(original, [])
    return {
        "format": COLUMNAR_FORMAT,
        "instructions": COLUMNAR_INSTRUCTIONS,
        "table_paths": paths,
        "data": data,
    }


def compact_tool_content(
    content: str, token_counter: Callable[[str], int], min_tokens: int = 1000
) -> str:
    """Return a smaller self-describing envelope, or the unchanged input.

    Savings include the envelope/decoding instructions and are measured against
    minified JSON, not formatting whitespace. Require at least 5% and 32 tokens
    of savings. ``token_counter`` is supplied by the caller's budget policy.
    """
    if not isinstance(content, str) or token_counter(content) < min_tokens:
        return content
    try:
        original = _parse_json(content)
        if not isinstance(original, (dict, list)) or _is_error_result(original):
            return content
        # Never recursively wrap an already encoded result (or a marker collision).
        if isinstance(original, dict) and original.get("format") == COLUMNAR_FORMAT:
            return content
        packed = _pack_columnar(original)
        if not packed["table_paths"]:
            return content
        encoded = _serialize(packed)
        baseline = token_counter(_serialize(original))
        savings = baseline - token_counter(encoded)
        if savings < max(32, baseline * 0.05):
            return content
        # A supplied tokenizer need not treat whitespace monotonically.
        if token_counter(encoded) >= token_counter(content):
            return content
        return encoded
    except (ValueError, TypeError, RecursionError, OverflowError):
        # Malformed/non-standard JSON must never become silently altered data.
        return content


def unpack_columnar(encoded):
    """Restore a compaction envelope without modifying it; reject invalid forms.

    Only paths explicitly recorded in a validated envelope are decoded, so an
    original object with its own ``columns``/``rows`` fields remains untouched.
    """
    envelope = _parse_json(encoded) if isinstance(encoded, str) else encoded
    if (
        not isinstance(envelope, dict)
        or set(envelope) != _ENVELOPE_KEYS
        or envelope.get("format") != COLUMNAR_FORMAT
        or envelope.get("instructions") != COLUMNAR_INSTRUCTIONS
        or not isinstance(envelope.get("data"), (dict, list))
        or not isinstance(envelope.get("table_paths"), list)
        or not envelope["table_paths"]
    ):
        raise ValueError("Not a columnar tool-result envelope")
    result = copy.deepcopy(envelope["data"])
    seen_paths = []
    for path in envelope["table_paths"]:
        if not isinstance(path, list) or any(type(part) not in (int, str) for part in path):
            raise ValueError("Invalid columnar table path")
        if any(path == previous or path[:len(previous)] == previous
               or previous[:len(path)] == path for previous in seen_paths):
            raise ValueError("Duplicate or overlapping columnar paths")
        seen_paths.append(path)
        node = result
        parent = None
        for part in path:
            parent = node
            if isinstance(node, dict) and isinstance(part, str) and part in node:
                node = node[part]
            elif isinstance(node, list) and type(part) is int and 0 <= part < len(node):
                node = node[part]
            else:
                raise ValueError("Columnar path does not address its declared container")
        if not isinstance(node, dict) or set(node) != {"columns", "rows"}:
            raise ValueError("Invalid columnar table")
        columns, rows = node["columns"], node["rows"]
        if (
            not isinstance(columns, list) or not columns
            or any(not isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(rows, list)
            or any(not isinstance(row, list) or len(row) != len(columns)
                   or any(isinstance(value, (dict, list)) for value in row) for row in rows)
        ):
            raise ValueError("Invalid columnar columns or row values")
        restored = [dict(zip(columns, row)) for row in rows]
        if not path:
            result = restored
        else:
            parent[path[-1]] = restored
    return result
