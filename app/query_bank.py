from __future__ import annotations

import re
from typing import Any

import yaml


ROOT_MAPPING_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")


def parse_query_bank_yaml(yaml_content: str) -> dict[str, Any]:
    transformed = _normalize_mixed_root_yaml(yaml_content)
    loaded = yaml.safe_load(transformed)
    if not isinstance(loaded, dict):
        raise ValueError("Query bank YAML must parse into a mapping")
    queries = loaded.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("Query bank queries must be a list")
    return loaded


def _normalize_mixed_root_yaml(yaml_content: str) -> str:
    lines = yaml_content.splitlines()
    result: list[str] = []
    in_queries = False
    inserted_queries = False

    for line in lines:
        stripped = line.lstrip()
        if not inserted_queries and line.startswith("- "):
            result.append("queries:")
            inserted_queries = True
            in_queries = True

        if in_queries:
            if line and not line.startswith(" ") and not line.startswith("- ") and ROOT_MAPPING_PATTERN.match(line):
                in_queries = False
            else:
                result.append(f"  {line}" if line else "  ")
                continue

        result.append(line)
    return "\n".join(result)
