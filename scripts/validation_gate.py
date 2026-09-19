#!/usr/bin/env python3
"""Measurable local validation gate for the Docker-targeted Validation build.

The script intentionally does not install packages or contact external services.
Run it from the repository root in the prepared/offline environment.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(name: str, command: list[str]) -> bool:
    print(f"\n=== {name} ===")
    print("$ " + " ".join(command))
    proc = subprocess.run(command, cwd=ROOT)
    if proc.returncode == 0:
        print(f"PASS: {name}")
        return True
    print(f"FAIL: {name} (exit {proc.returncode})")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validation engineering acceptance gate")
    parser.add_argument("--docker", action="store_true", help="Also run Docker Compose validation and image build")
    parser.add_argument("--integration", action="store_true", help="Run Router integration/recovery tests")
    args = parser.parse_args()

    python = sys.executable
    steps: list[tuple[str, list[str]]] = [
        ("Python compile", [python, "-m", "compileall", "-q", "Validation"]),
        (
            "Parser contract and source tests",
            [
                python, "-m", "unittest",
                "Validation.Data_Parser.tests.test_xml_contract",
                "Validation.Data_Parser.tests.test_real_source_samples",
                "Validation.Data_Parser.tests.test_processor_spooling",
                "Validation.Data_Parser.tests.test_semantic_audit",
                "Validation.Data_Parser.tests.test_spoofing",
            ],
        ),
        (
            "Full pipeline acceptance",
            [
                python, "-m", "unittest",
                "Validation.tests.test_full_pipeline_acceptance",
            ],
        ),
    ]

    if args.integration:
        steps.append((
            "Router integration and recovery tests",
            [
                python, "-m", "unittest",
                "Validation.Data_Router.tests.integration.test_file_routing",
                "Validation.Data_Router.tests.integration.test_tcp_routing",
                "Validation.Data_Router.tests.integration.test_restart_semantics",
                "Validation.Data_Router.tests.integration.test_fault_recovery",
                "Validation.Data_Router.tests.integration.test_failure_scenarios",
            ],
        ))

    if args.docker:
        steps.extend([
            ("Docker Compose syntax", ["docker", "compose", "config", "--quiet"]),
            ("Docker image build", ["docker", "build", "-f", "docker/Dockerfile", "-t", "validation/parser:gate", "."]),
        ])

    results = [run_step(name, command) for name, command in steps]
    passed = sum(results)
    total = len(results)
    print(f"\nVALIDATION GATE: {passed}/{total} steps passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
