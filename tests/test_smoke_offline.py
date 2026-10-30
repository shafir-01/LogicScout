"""Run the non-live smoke checks against an in-process TestClient (no network, no keys)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import smoke  # noqa: E402
from logicscout.server import app as appmod  # noqa: E402


def test_static_smoke_checks():
    with TestClient(appmod.create_app()) as c:
        results = smoke.run_static_checks(c)
    dist_missing = not (appmod.DIST / "index.html").exists()
    failed = [(n, d) for n, ok, d in results
              if not ok and not (dist_missing and n in ("static index", "spa routes"))]
    assert not failed, failed
    assert len(results) == 8
    if dist_missing:
        pytest.skip("web/dist not built; API checks passed")
