"""
Mutation Testing Engine for Observability (ADR-064).
Systematically mutates AST / expressions in toolkit/features/observability.py
and verifies 100% Mutant Kill Rate (zero surviving mutants).
"""

import subprocess
import sys
from pathlib import Path

TARGET_FILE = Path("toolkit/features/observability.py")
TEST_COMMAND = ["poetry", "run", "pytest", "tests/test_observability.py", "-o", "addopts=''", "-q"]

MUTATIONS = [
    # 1. Mutate time offset logic
    ("minutes=15", "minutes=30", "Mutate default time offset from 15m to 30m"),
    (
        "val, unit = int(match.group(1)), match.group(2)",
        "val, unit = int(match.group(1)) + 1, match.group(2)",
        "Mutate time offset value parsing",
    ),
    # 2. Mutate deduplication regex
    (r"\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?\]?", r"\d{4}", "Corrupt timestamp regex normalization"),
    ("count > 1", "count > 2", "Mutate deduplication count threshold to > 2"),
    ("Repeated {count}x", "Duplicate {count}x", "Mutate repeated badge text"),
    # 3. Mutate Loki LogQL stream parsing
    ('query: str, since: str = "15m"', 'query: str, since: str = "1h"', "Mutate default since window in LokiClient"),
    ('status == "success"', 'status == "failed"', "Invert Loki API response status check"),
    ("level.lower()", "level.upper()", "Corrupt log level lowercase filter"),
    # 4. Mutate Alertmanager state parsing
    ('item.get("state", "unknown")', '"firing"', "Force alert state to constant 'firing'"),
    ('item.get("labels", {}).get("severity", "info")', '"critical"', "Force alert severity to constant 'critical'"),
    # 5. Mutate Slack SRE Client
    ("not self.token", "bool(self.token)", "Invert Slack token mock mode check"),
    ('f"#{channel}"', "channel", "Disable channel '#' prefix resolution"),
    # 6. Mutate Diagnostic Classifier (Root Cause Engine)
    ('severity = "CRITICAL"', 'severity = "INFO"', "Downgrade OOMKilled severity to INFO"),
    (
        '"oom" in first_error.lower() or "137" in first_error',
        '"oom" in first_error.lower() and "137" in first_error',
        "Change OR to AND in OOMKilled signature",
    ),
    (
        '"502" in first_error or "connection refused" in first_error.lower()',
        "False",
        "Disable Connection Refused signature detection",
    ),
    ('"timeout" in first_error.lower()', "False", "Disable Timeout signature detection"),
    ("first_error[:120]", "first_error[:10]", "Truncate Application Exception detail to 10 chars"),
]


def run_mutation_tests() -> None:
    original_code = TARGET_FILE.read_text(encoding="utf-8")
    total_mutants = len(MUTATIONS)
    killed = 0
    survived = 0

    print(f"=== Running Mutation Testing on {TARGET_FILE} ({total_mutants} Mutants) ===")

    for i, (orig, mutated, desc) in enumerate(MUTATIONS, 1):
        if orig not in original_code:
            print(f"[{i}/{total_mutants}] SKIP: Target pattern '{orig}' not found in source.")
            continue

        # Apply mutant
        mutated_code = original_code.replace(orig, mutated, 1)
        TARGET_FILE.write_text(mutated_code, encoding="utf-8")

        # Run test suite
        res = subprocess.run(TEST_COMMAND, capture_output=True, text=True)

        if res.returncode != 0:
            killed += 1
            print(f"[{i}/{total_mutants}] KILLED: {desc}")
        else:
            survived += 1
            print(f"[{i}/{total_mutants}] SURVIVED (DEFECT): {desc}")

    # Restore original file
    TARGET_FILE.write_text(original_code, encoding="utf-8")

    mutation_score = (killed / total_mutants) * 100
    print("\n================ Mutation Testing Results ================")
    print(f"Total Mutants: {total_mutants}")
    print(f"Killed:        {killed}")
    print(f"Survived:      {survived}")
    print(f"Mutation Score: {mutation_score:.1f}%")
    print("==========================================================")

    if survived > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_mutation_tests()
