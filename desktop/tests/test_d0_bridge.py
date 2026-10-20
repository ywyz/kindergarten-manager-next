"""R6: Node regression for the host-bridge readiness helper.

The page must wait for the actual ``get_session`` function, not merely for
``window.pywebview`` to exist. The helper's delay/timeout behaviour is tested
deterministically in Node (TypeScript stripped), so no real WebView2 window
is needed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE_TEST = REPO_ROOT / "frontend" / "src" / "d0" / "bridge.test.mjs"


def test_bridge_readiness_regression():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    result = subprocess.run(
        [node, str(BRIDGE_TEST)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK bridge readiness" in result.stdout
