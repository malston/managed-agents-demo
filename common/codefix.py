"""The code-fix scenario, shared by demos 2 and 3.

The top error in sample/app.log is "upstream timeout calling stripe-gw after
30000ms". The settings say 3s. sample/payments-svc has the bug that turns 3s into
30000ms. The agent gets the log and the service, and has to find the code behind
the error, write a failing test, fix the code and get the tests to pass.

verify() checks the result the same way for every option, without a model.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from common import DEFAULT_LOG, REPO_ROOT

SERVICE = REPO_ROOT / "sample" / "payments-svc"
TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]

TASK = """app.log is the production log for payments-svc, whose code is in this
folder. Find the code behind the most frequent ERROR in the log. Write a
regression test that fails because of the bug, fix the code, and run the tests
until they all pass. Then write FIX.md with the root cause, the log line that
pointed to it, the files you changed and the test you added."""


def prepare_workspace(dest: Path, log: Path = DEFAULT_LOG, with_claude_setup: bool = True) -> Path:
    """Copy the service and the log into a fresh folder. Returns the folder.

    with_claude_setup=False drops CLAUDE.md and .claude/, for harnesses that
    wouldn't read them anyway.
    """
    if dest.exists():
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns("__pycache__", *(() if with_claude_setup else ("CLAUDE.md", ".claude")))
    shutil.copytree(SERVICE, dest, ignore=ignore)
    shutil.copy(log, dest / "app.log")
    return dest


def clean_env() -> dict[str, str]:
    """Environment for running the service's tests: no cloud or API credentials."""
    keep = ("PATH", "HOME", "LANG", "SYSTEMROOT", "TMPDIR")
    return {k: v for k, v in os.environ.items() if k in keep} | {"PYTHONDONTWRITEBYTECODE": "1"}


def run_tests(workdir: Path, timeout: int = 60) -> tuple[bool, str]:
    """Run the service's test suite. Returns (passed, combined output)."""
    try:
        proc = subprocess.run(
            TEST_COMMAND, cwd=workdir, env=clean_env(), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out after {timeout}s."
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]


@dataclass
class FixCheck:
    tests_pass: bool
    bug_fixed: bool  # parse_duration_ms("3s") == 3000
    tests_added: int  # test methods beyond the 5 the service ships with
    settings_untouched: bool
    fix_note: bool  # FIX.md written

    @property
    def ok(self) -> bool:
        return self.tests_pass and self.bug_fixed and self.tests_added > 0 and self.settings_untouched

    def summary(self) -> str:
        marks = {True: "yes", False: "NO"}
        return (
            f"tests pass: {marks[self.tests_pass]}, bug fixed: {marks[self.bug_fixed]}, "
            f"tests added: {self.tests_added}, settings untouched: {marks[self.settings_untouched]}, "
            f"FIX.md: {marks[self.fix_note]}"
        )


ORIGINAL_TEST_COUNT = 5


def verify(workdir: Path) -> FixCheck:
    """Check the agent's work: the suite passes, the bug is gone, a test was added."""
    passed, _ = run_tests(workdir)
    probe = subprocess.run(
        [sys.executable, "-c", "from payments.durations import parse_duration_ms as p; print(p('3s'))"],
        cwd=workdir,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    test_count = sum(
        len(re.findall(r"^\s+def test_", path.read_text(), flags=re.M))
        for path in (workdir / "tests").glob("test_*.py")
    )
    settings = (workdir / "payments" / "settings.py").read_text()
    return FixCheck(
        tests_pass=passed,
        bug_fixed=probe.stdout.strip() == "3000",
        tests_added=test_count - ORIGINAL_TEST_COUNT,
        settings_untouched=settings == (SERVICE / "payments" / "settings.py").read_text(),
        fix_note=(workdir / "FIX.md").exists(),
    )
