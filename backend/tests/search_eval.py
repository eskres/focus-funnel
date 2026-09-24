"""Loads the search evaluation set in tests/fixtures/search_eval/."""

from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).parent / "fixtures" / "search_eval"


def load_eval_set() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    thoughts = yaml.safe_load((EVAL_DIR / "thoughts.yaml").read_text())["thoughts"]
    queries = yaml.safe_load((EVAL_DIR / "queries.yaml").read_text())["queries"]
    return thoughts, queries
