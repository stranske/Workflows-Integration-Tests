# Test Suite for Workflows-Integration-Tests

This test suite provides comprehensive coverage for the integration test repository.

## Test Files

### `test_example.py`
- **Source**: Synced from `stranske/Workflows/templates/integration-repo/`
- **Purpose**: Basic smoke test for the example module
- **Coverage**: 100% of `src/example/__init__.py`

### `test_sync_test_dependencies.py`
- **Source**: Local (this chat session)
- **Purpose**: Comprehensive tests for `scripts/sync_test_dependencies.py`
- **Coverage**: 85.71% (only missing `if __name__ == "__main__"` line)
- **Tests**:
  - `--verify` flag handling
  - `--fix` flag handling
  - No arguments case
  - Multiple flags together
  - Command-line invocation

### `test_sync_tool_versions.py`
- **Source**: Local (this chat session)
- **Purpose**: Comprehensive tests for `scripts/sync_tool_versions.py`
- **Coverage**: 85.71% (only missing `if __name__ == "__main__"` line)
- **Tests**:
  - `--check` flag handling
  - `--apply` flag handling
  - No arguments case
  - Multiple flags together
  - Command-line invocation

### `test_resolve_mypy_pin.py`
- **Source**: Local (this chat session)
- **Purpose**: Comprehensive tests for `tools/resolve_mypy_pin.py`
- **Coverage**: 88.89% (only missing `if __name__ == "__main__"` line)
- **Tests**:
  - GITHUB_OUTPUT file writing
  - Local execution (no GITHUB_OUTPUT)
  - Default Python version (3.11)
  - Custom Python version handling
  - Command-line invocation

### `test_script_execution.py`
- **Source**: Local (this chat session)
- **Purpose**: Integration tests for script execution as standalone programs
- **Coverage**: Not applicable (subprocess execution)
- **Tests**:
  - Running `sync_test_dependencies.py` as a script
  - Running `sync_tool_versions.py` as a script
  - Running `resolve_mypy_pin.py` as a script

## Coverage Summary

**Overall: 87.50%** (40 statements, 3 missed, 8 branches, 3 partial)

The 3 missed lines are all `if __name__ == "__main__": sys.exit(main())` blocks, which are standard boilerplate and typically excluded from coverage requirements.

| Module | Statements | Missing | Branches | Partial | Coverage |
|--------|------------|---------|----------|---------|----------|
| `src/example/__init__.py` | 2 | 0 | 0 | 0 | **100.00%** |
| `tools/resolve_mypy_pin.py` | 14 | 1 | 4 | 1 | **88.89%** |
| `scripts/sync_test_dependencies.py` | 12 | 1 | 2 | 1 | **85.71%** |
| `scripts/sync_tool_versions.py` | 12 | 1 | 2 | 1 | **85.71%** |

## Running Tests

### Full test suite with coverage:
```bash
pytest --cov=src --cov=scripts --cov=tools --cov-report=term --cov-report=html
```

### Run specific test file:
```bash
pytest tests/test_sync_test_dependencies.py -v
```

### View HTML coverage report:
```bash
python -m http.server --directory htmlcov
```

## Test Philosophy

Even though the scripts/tools in this repo are stubs (minimal implementations), we maintain comprehensive test coverage because:

1. **Validates behavior**: Tests document expected behavior for consumers
2. **Catches regressions**: Any changes to stubs are caught immediately
3. **Demonstrates patterns**: Shows how to test CLI scripts properly
4. **Example for consumers**: Real consumer repos can reference these tests

## CI Integration

These tests run automatically in CI via `.github/workflows/ci.yml`, which calls the reusable workflow:
```yaml
uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@v1
```

The CI validates:
- All tests pass across Python 3.11, 3.12, 3.13
- Code coverage meets standards
- Scripts can be executed as expected
