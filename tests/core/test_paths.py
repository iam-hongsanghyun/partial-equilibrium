"""PE_PROJECT_DIR path-resolution regression test (Vercel/wheel-install fix).

`pe.core.paths.PROJECT_DIR` is computed from `Path(__file__).resolve().parents[3]`
by default -- correct for a local EDITABLE install where `pe.core.paths` IS
the repo file (`<repo>/core/backend/core/paths.py`), but wrong for a WHEEL
install away from the repo checkout (Vercel: WO-0 switched deployment to
`pip install .` from `requirements.txt`, so this module resolves inside
site-packages and `parents[3]` no longer points at the checkout that holds
`core/frontend/dist/`, `examples/`, `docs/`). The fix: `PROJECT_DIR` resolves
from the `PE_PROJECT_DIR` env var first, falling back to `parents[3]`
unchanged when unset -- and `api/index.py` (the Vercel entry point) sets that
env var to the checkout root before importing `pe`.

Algorithm:
    Not a numerical algorithm -- a path-resolution / process-boundary test.
    `pe.core.paths` resolves `PROJECT_DIR` at IMPORT time, so only a fresh
    interpreter observes a change in `PE_PROJECT_DIR` (this test process may
    already have `pe.core.paths` cached in `sys.modules` from collection or
    an earlier test). Each case spawns `sys.executable -c <code>` with an
    explicit `env=` (never inherited/merged implicitly), has the child print
    the paths under test, and asserts on the child's stdout.

References:
    TODO.md, "Pre-main-merge blocker (restructure introduced): Vercel/wheel
    path resolution".
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _clean_env() -> dict[str, str]:
    """Copy of the current process environment with ``PE_PROJECT_DIR`` unset.

    Returns:
        A fresh ``dict`` (mutating it never affects ``os.environ``) that
        omits ``PE_PROJECT_DIR`` regardless of whether the parent shell
        happens to export one, so "env unset" is deterministic.
    """
    env = dict(os.environ)
    env.pop("PE_PROJECT_DIR", None)
    return env


def _run_python(code: str, *, env: dict[str, str]) -> str:
    """Run ``code`` to completion in a fresh interpreter with an explicit env.

    Args:
        code: A ``python -c`` program body. Must print every value under
            test, one per line -- this is the only channel back to the
            parent process (``sys.modules`` in the parent is not reset
            between test cases).
        env: Complete environment for the child process. Callers pass
            ``_clean_env()`` (optionally with ``PE_PROJECT_DIR`` added) so
            the child's view of the variable is exact, not merged
            implicitly with whatever this test process inherited.

    Returns:
        The child process's stdout, with trailing whitespace stripped.

    Raises:
        AssertionError: if the child process exits non-zero; the message
            includes stderr for debuggability.
    """
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, (
        f"child process failed (exit {result.returncode}):\n{result.stderr}"
    )
    return result.stdout.strip()


def test_project_dir_defaults_to_repo_root_when_env_unset() -> None:
    """(a) Bit-identity proof: ``PE_PROJECT_DIR`` unset resolves exactly as before.

    Every local dev workflow and the test suite itself run with
    ``PE_PROJECT_DIR`` unset, so ``PROJECT_DIR`` must fall back to
    ``parents[3]`` -- the repo root -- unchanged from before the env-var
    anchor existed.
    """
    stdout = _run_python(
        "from pe.core.paths import PROJECT_DIR\nprint(PROJECT_DIR)\n",
        env=_clean_env(),
    )
    assert Path(stdout) == REPO_ROOT


def test_project_dir_rerooted_under_pe_project_dir_when_set(tmp_path: Path) -> None:
    """(b) ``PE_PROJECT_DIR`` set re-roots ``PROJECT_DIR`` and every derived dir.

    Simulates the wheel-install-away-from-repo case (Vercel): the derived
    dirs (``EXAMPLES_DIR``, ``FRONTEND_DIST_DIR``, ``DOCS_DIR``) must track
    the override, not the module's own on-disk location.
    """
    env = _clean_env()
    env["PE_PROJECT_DIR"] = str(tmp_path)
    stdout = _run_python(
        "from pe.core import paths\n"
        "print(paths.PROJECT_DIR)\n"
        "print(paths.EXAMPLES_DIR)\n"
        "print(paths.FRONTEND_DIST_DIR)\n"
        "print(paths.DOCS_DIR)\n",
        env=env,
    )
    project_dir, examples_dir, frontend_dist_dir, docs_dir = (
        Path(line) for line in stdout.splitlines()
    )
    resolved_root = tmp_path.resolve()
    assert project_dir == resolved_root
    assert examples_dir == resolved_root / "examples"
    assert frontend_dist_dir == resolved_root / "core" / "frontend" / "dist"
    assert docs_dir == resolved_root / "docs"


def test_api_index_sets_pe_project_dir_before_importing_pe() -> None:
    """(c) ``api/index.py`` (the Vercel entry) pins ``PE_PROJECT_DIR`` pre-import.

    Reproduces the Vercel import smoke test: with ``PE_PROJECT_DIR`` unset in
    the child's starting environment, importing ``api.index`` must (1) set
    ``PE_PROJECT_DIR`` to the checkout root itself before ``pe`` is
    imported, and (2) still successfully resolve ``from pe.web.server import
    app`` -- proving the wheel-sim env-anchor doesn't break the app import.
    """
    stdout = _run_python(
        "import sys, os\n"
        "sys.path[:0] = ['.']\n"
        "from api.index import PROJECT_DIR, app\n"
        "assert app is not None\n"
        "print(os.environ['PE_PROJECT_DIR'])\n"
        "print(PROJECT_DIR)\n",
        env=_clean_env(),
    )
    env_value, project_dir_repr = stdout.splitlines()
    assert Path(env_value) == REPO_ROOT
    assert env_value == project_dir_repr
