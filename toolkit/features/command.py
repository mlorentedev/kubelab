"""Command execution utilities for running shell commands and processes."""

import subprocess
from pathlib import Path

from toolkit.core.logging import ExecutionError, logger


def run(
    command: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command with proper error handling."""
    logger.debug(f"Running command: {command}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=capture_output,
            text=True,
            check=check,
        )

        if result.stdout:
            logger.debug(f"Command stdout: {result.stdout}")

        return result

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        raise ExecutionError(command, e.returncode, e.stdout, stderr) from e


def run_list(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    check: bool = True,
    stream_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command from a list with proper error handling."""
    logger.debug(f"Running command: {' '.join(command)}")

    try:
        if stream_output:
            result = subprocess.run(command, cwd=cwd, env=env, text=True, check=check)
            return subprocess.CompletedProcess(command, result.returncode if result else 0, "", "")
        else:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=capture_output,
                text=True,
                check=check,
            )

            if result.stdout:
                logger.debug(f"Command stdout: {result.stdout}")

            return result

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        command_str = " ".join(command)
        raise ExecutionError(command_str, e.returncode, e.stdout, stderr) from e
