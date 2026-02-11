 Testing Guide

This document describes the testing strategy and practices for the cubelab.cloud project.

 Testing Philosophy

- Test-first mindset: Write tests for new features
- High coverage: Target %+ overall, %+ for core modules
- Fast feedback: Unit tests run in milliseconds
- Automated: Tests run in CI/CD on every push
- Type-safe: All test code uses strict type hints

 Test Organization

 Test Structure

```
tests/
 conftest.py               Shared fixtures and configuration
 test_cli/                 CLI command tests
 test_core/                Core functionality tests
 test_config/              Configuration tests
 test_features/            Feature implementation tests
```

 Test Types

Unit Tests (`@pytest.mark.unit`)
- Fast, isolated tests
- Mock external dependencies
- Test single functions/classes
- Should run in <  second total

Integration Tests (`@pytest.mark.integration`)
- Test multiple components together
- May require Docker/external services
- Test real filesystem/network operations
- Slower but comprehensive

Slow Tests (`@pytest.mark.slow`)
- Long-running operations
- Full end-to-end workflows
- Skipped during rapid development

 Running Tests

 Quick Start

```bash
 Run all tests
poetry run pytest

 Run with coverage
poetry run pytest --cov=toolkit

 Run only fast unit tests
poetry run pytest -m unit

 Watch mode (requires pytest-watch)
poetry run ptw
```

 Detailed Commands

```bash
 Run specific test file
poetry run pytest tests/test_core/test_logging.py

 Run specific test class
poetry run pytest tests/test_core/test_logging.py::TestPlatformLogger

 Run specific test
poetry run pytest tests/test_core/test_logging.py::TestPlatformLogger::test_logger_initialization

 Run with verbose output
poetry run pytest -v

 Run tests matching pattern
poetry run pytest -k "logging"

 Show test output (don't capture)
poetry run pytest -s

 Stop on first failure
poetry run pytest -x

 Run last failed tests
poetry run pytest --lf
```

 Coverage Reports

```bash
 Terminal report with missing lines
poetry run pytest --cov=toolkit --cov-report=term-missing

 HTML report (opens in browser)
poetry run pytest --cov=toolkit --cov-report=html
open htmlcov/index.html

 XML report (for CI/CD)
poetry run pytest --cov=toolkit --cov-report=xml

 All report formats
poetry run pytest --cov=toolkit --cov-report=html --cov-report=xml --cov-report=term
```

 Writing Tests

 Basic Test Structure

```python
"""Tests for toolkit.features.example module."""

import pytest
from toolkit.features.example import ExampleClass


@pytest.mark.unit
class TestExampleClass:
    """Test ExampleClass functionality."""

    def test_initialization(self) -> None:
        """Test class initialization."""
        obj = ExampleClass(name="test")
        assert obj.name == "test"

    def test_validation(self) -> None:
        """Test input validation."""
        with pytest.raises(ValueError, match="Invalid name"):
            ExampleClass(name="")
```

 Using Fixtures

```python
@pytest.fixture
def example_config(temp_dir: Path) -> Path:
    """Create example configuration file."""
    config_file = temp_dir / "config.yml"
    config_file.write_text("setting: value\n")
    return config_file


def test_with_fixture(example_config: Path) -> None:
    """Test using fixture."""
    assert example_config.exists()
    content = example_config.read_text()
    assert "setting" in content
```

 Mocking

```python
from unittest.mock import MagicMock, patch, call


@patch("toolkit.features.system.subprocess.run")
def test_command_execution(mock_run: MagicMock) -> None:
    """Test command execution."""
    mock_run.return_value.returncode = 
    mock_run.return_value.stdout = "success"

    result = run_command("docker ps")

    mock_run.assert_called_once_with(
        ["docker", "ps"],
        capture_output=True,
        text=True
    )
    assert result == "success"
```

 Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("dev", "development"),
    ("staging", "staging"),
    ("prod", "production"),
])
def test_environment_names(input: str, expected: str) -> None:
    """Test environment name normalization."""
    assert normalize_env_name(input) == expected
```

 Testing Exceptions

```python
def test_invalid_config_raises_error() -> None:
    """Test invalid configuration raises ConfigurationError."""
    with pytest.raises(ConfigurationError, match="Invalid config"):
        load_config("/nonexistent/path")


def test_validation_error_message() -> None:
    """Test validation error includes details."""
    try:
        validate_config_file("invalid.yaml")
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        assert "invalid.yaml" in str(e)
        assert e.exit_code == 
```

 CI/CD Integration

 GitHub Actions Workflow

Tests run automatically on every push:

```yaml
- name: Install dependencies
  run: poetry install

- name: Run tests with coverage
  run: poetry run pytest --cov=toolkit --cov-report=xml

- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v
  with:
    files: ./coverage.xml
    flags: unittest
```

 Pre-commit Hooks

Tests can run before commits (optional):

```yaml
 In .pre-commit-config.yaml
- repo: local
  hooks:
    - id: pytest-check
      name: pytest-check
      entry: poetry run pytest -m unit
      language: system
      pass_filenames: false
      always_run: true
```

 Coverage Goals

| Component | Target | Current |
|-----------|--------|---------|
| Overall   | %    | TBD     |
| Core      | %    | TBD     |
| CLI       | %    | TBD     |
| Features  | %    | TBD     |

View coverage: `poetry run pytest --cov=toolkit --cov-report=html`

 Test Best Practices

 Do

 Write descriptive test names
```python
def test_config_validation_fails_for_missing_required_vars() -> None:
    """Test config file validation detects missing required variables."""
```

 One assertion per test (when possible)
```python
def test_logger_has_correct_name() -> None:
    """Test logger name matches initialization."""
    logger = PlatformLogger("test")
    assert logger.logger.name == "test"
```

 Use fixtures for setup
```python
def test_with_temp_directory(temp_dir: Path) -> None:
    """Test file operations in temporary directory."""
    test_file = temp_dir / "test.txt"
    test_file.write_text("content")
    assert test_file.read_text() == "content"
```

 Mock external dependencies
```python
@patch("toolkit.features.system.docker_client")
def test_container_operations(mock_docker: MagicMock) -> None:
    """Test container operations without real Docker."""
    mock_docker.containers.list.return_value = []
    containers = get_running_containers()
    assert containers == []
```

 Don't

 Don't test implementation details
```python
 Bad: Testing internal method
def test_internal_helper_method() -> None:
    obj = MyClass()
    assert obj._internal_helper() == "value"

 Good: Test public interface
def test_public_method() -> None:
    obj = MyClass()
    assert obj.process() == "expected_result"
```

 Don't rely on test execution order
```python
 Bad: Tests depend on each other
class TestBadExample:
    data = None

    def test__setup(self) -> None:
        self.data = "value"

    def test__use_data(self) -> None:
        assert self.data == "value"   Fails if run alone!

 Good: Each test is independent
class TestGoodExample:
    def test_with_fixture(self, shared_data: str) -> None:
        assert shared_data == "value"
```

 Don't use real filesystem paths
```python
 Bad: Uses real filesystem
def test_file_operations() -> None:
    Path("/tmp/test.txt").write_text("content")

 Good: Uses temp_dir fixture
def test_file_operations(temp_dir: Path) -> None:
    (temp_dir / "test.txt").write_text("content")
```

 Common Testing Patterns

 Testing CLI Commands

```python
from typer.testing import CliRunner
from toolkit.main import app

runner = CliRunner()


def test_services_list_command() -> None:
    """Test 'toolkit services list' command."""
    result = runner.invoke(app, ["services", "list"])
    assert result.exit_code == 
    assert "api" in result.stdout
```

 Testing File Operations

```python
def test_compose_config_validation(temp_dir: Path) -> None:
    """Test compose configuration validation."""
    base_file = temp_dir / "compose.base.yml"
    base_file.write_text("services:\n  web:\n    image: nginx\n")

    overlay_file = temp_dir / "compose.dev.yml"
    overlay_file.write_text("services:\n  web:\n    ports:\n      - '8080:80'\n")

    assert base_file.exists()
    assert overlay_file.exists()
```

 Testing Configuration

```python
def test_environment_config_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test environment configuration loading."""
    monkeypatch.setenv("PLATFORM_ENVIRONMENT", "staging")

    config = load_environment_config()

    assert config.name == "staging"
    assert config.requires_confirmation is True
```

 Debugging Tests

 Print Debug Information

```python
def test_with_debug_output(capsys: pytest.CaptureFixture) -> None:
    """Test with captured output."""
    print("Debug info")   Will be captured
    result = some_function()

    captured = capsys.readouterr()
    assert "Debug info" in captured.out
```

 Use Pytest Debug

```bash
 Start debugger on failure
poetry run pytest --pdb

 Start debugger on error
poetry run pytest --pdbcls=IPython.terminal.debugger:TerminalPdb

 Show local variables on failure
poetry run pytest --showlocals
```

 VS Code Debugging

```json
{
  "version": "..",
  "configurations": [
    {
      "name": "Python: Pytest",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["-v"],
      "console": "integratedTerminal"
    }
  ]
}
```

 Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Python Testing with pytest (Book)](https://pragprog.com/titles/bopytest/)
- [Real Python: Testing Guide](https://realpython.com/pytest-python-testing/)
- [Effective Python Testing](https://effectivepython.com/)

 Troubleshooting

Tests not discovered:
- Ensure test files start with `test_`
- Ensure test functions start with `test_`
- Check `pytest.ini` configuration

Import errors:
```bash
poetry install
poetry run pytest
```

Slow tests:
```bash
 Show slowest  tests
poetry run pytest --durations=

 Skip slow tests
poetry run pytest -m "not slow"
```

Coverage not showing:
```bash
 Ensure pytest-cov is installed
poetry install --with dev

 Check coverage configuration in pyproject.toml
```

 Contributing Tests

When contributing:

. Write tests for new features - No PR without tests
. Maintain coverage - Don't decrease overall coverage
. Follow conventions - Use existing test patterns
. Document complex tests - Add docstrings explaining "why"
. Keep tests fast - Unit tests should be < ms each

See `CONTRIBUTING.md` for more details.
