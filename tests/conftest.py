from datetime import datetime, timezone

import pytest

from agent import config
from agent.code_store import InMemoryCodeStore
from agent.data import load_datasets
from agent.registry import Deps

FIXED_NOW = datetime(2026, 11, 3, 17, 30, tzinfo=timezone.utc)  # 09:30 PT


@pytest.fixture(scope="session")
def datasets():
    return load_datasets(config.DATA_DIR)


@pytest.fixture
def deps(datasets, tmp_path):
    return Deps(
        datasets=datasets,
        now=lambda: FIXED_NOW,
        handoff_log=tmp_path / "handoffs.jsonl",
        code_store=InMemoryCodeStore(),
    )
