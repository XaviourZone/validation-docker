#!/usr/bin/env python3
"""Static release-document consistency checks for the Validation branch."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BRANCH = "dev/validation-full-build"


def main() -> int:
    task = (ROOT / "docs/71-tasking.md").read_text(encoding="utf-8")
    progress = (ROOT / "docs/progress.md").read_text(encoding="utf-8")
    release = (ROOT / "docs/release-readiness.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    checks = {
        "branch tasking": f"Development branch: {BRANCH}" in task or f"Branch: {BRANCH}" in task,
        "branch progress": f"Development branch: {BRANCH}" in progress,
        "branch release": f"Branch: {BRANCH}" in release,
        "full gate CI": "Run complete Validation gate" in workflow,
        "task 62 complete": re.search(r"62\. ☑", task) is not None,
        "task 69 complete": re.search(r"69\. ☑", task) is not None,
        "task 71 complete": re.search(r"71\. ☑", task) is not None,
        "41-field coverage documented": "field coverage" in task.lower() and "41-field" in progress,
        "environment evidence explicit": "environment-dependent" in release,
    }

    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL") + f": {name}")

    if failed:
        print("Release documentation consistency failed:", ", ".join(failed))
        return 1
    print("PASS: Release documentation consistency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
