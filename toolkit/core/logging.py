"""Enhanced logging configuration with Rich integration and custom exceptions."""

import logging
import sys
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt

# Removed static import of settings to avoid circular dependency
# from toolkit.config.settings import settings

# =============================================================================
# Custom Exceptions
# =============================================================================


class PlatformError(Exception):
    """Base exception for platform CLI errors."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ConfigurationError(PlatformError):
    """Raised when there's a configuration error."""

    pass


class EnvironmentError(PlatformError):
    """Raised when there's an environment-related error."""

    pass


class ValidationError(PlatformError):
    """Raised when validation fails."""

    pass


class DependencyError(PlatformError):
    """Raised when required dependencies are missing."""

    def __init__(self, missing_tools: list[str]) -> None:
        tools_list = ", ".join(missing_tools)
        message = f"Missing required dependencies: {tools_list}"
        super().__init__(message)
        self.missing_tools = missing_tools


class ExecutionError(PlatformError):
    """Raised when command execution fails."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        message = f"Command '{command}' failed with exit code {exit_code}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message, exit_code)
        self.command = command
        self.stdout = stdout
        self.stderr = stderr


class FileNotFoundError(PlatformError):
    """Raised when required files are not found."""

    def __init__(self, file_path: str) -> None:
        message = f"Required file not found: {file_path}"
        super().__init__(message)
        self.file_path = file_path


# Global console instance
console = Console()


class PlatformLogger:
    """Enhanced logger with Rich formatting and user interaction."""

    def __init__(self, name: str = "platform-cli") -> None:
        """Initialize the logger."""
        self.logger = logging.getLogger(name)
        self.console = console
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Set up Rich logging handler with defaults."""
        if self.logger.handlers:
            return  # Already configured

        handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            show_time=False,
        )

        # Defaults (safe without settings)
        log_format = "%(message)s"
        log_level = "INFO"

        # Try to load settings dynamically, but fail silently if circular import
        try:
            from toolkit.config.settings import settings

            log_level = settings.log_level
            if settings.log_format.lower() == "json":
                log_format = "%(levelname)s - %(name)s - %(message)s"
            else:
                log_format = settings.log_format
        except (ImportError, AttributeError, RuntimeError):
            # If settings aren't ready, use defaults
            pass

        handler.setFormatter(logging.Formatter(log_format))
        self.logger.addHandler(handler)
        self.logger.setLevel(getattr(logging, log_level.upper()))

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message with blue prefix."""
        console.print(f"[blue][INFO][/blue] {message}", **kwargs)

    def success(self, message: str, **kwargs: Any) -> None:
        """Log success message with green prefix."""
        console.print(f"[green][SUCCESS][/green] {message}", **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with yellow prefix."""
        console.print(f"[yellow][WARNING][/yellow] {message}", **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message with red prefix."""
        console.print(f"[red][ERROR][/red] {message}", **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message and exit."""
        console.print(f"[bold red][CRITICAL][/bold red] {message}", **kwargs)
        sys.exit(1)

    def section(self, title: str) -> None:
        """Print a section header."""
        console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
        console.print(f"[bold cyan]{title.center(60)}[/bold cyan]")
        console.print(f"[bold cyan]{'=' * 60}[/bold cyan]\n")

    def subsection(self, title: str) -> None:
        """Print a subsection header."""
        console.print(f"\n[bold blue]--- {title} ---[/bold blue]\n")

    def confirm(
        self,
        message: str,
        default: bool = False,
        show_default: bool = True,
    ) -> bool:
        """Ask for user confirmation."""
        return Confirm.ask(message, default=default, show_default=show_default)

    def prompt(
        self,
        message: str,
        default: str | None = None,
        choices: list[str] | None = None,
    ) -> str:
        """Prompt user for input."""
        return Prompt.ask(message, default=default or "", choices=choices)

    def progress(self, description: str = "Processing...") -> Progress:
        """Create a progress context manager."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        )

    def table(self, title: str) -> Any:
        """Create a Rich table with standard styling."""
        from rich.table import Table

        table = Table(title=title, show_header=True, header_style="bold cyan")
        return table


# Global logger instance
logger = PlatformLogger()


def get_logger(name: str = "toolkit") -> PlatformLogger:
    """Get a logger instance for a specific module.

    Args:
        name: The logger name, typically __name__ of the calling module

    Returns:
        PlatformLogger instance

    Note: Currently returns the global logger instance for consistency.
    In the future, this could be extended to create module-specific loggers.
    """
    # For now, return the global logger instance to maintain consistency
    # This could be extended later to create module-specific loggers if needed
    return logger
