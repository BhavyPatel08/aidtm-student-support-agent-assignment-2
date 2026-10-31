import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path):
    config.RUNTIME = tmp_path
    config.CONTROLS_ENABLED = True
    yield
