# CLAUDE.md - Integration Test Repository

> **READ THIS FIRST** - This repository validates the stranske/Workflows workflow library.

## Purpose

This repository exists to:
1. **Validate reusable workflows** from stranske/Workflows work correctly
2. **Test template synchronization** to consumer repos
3. **Provide live examples** of workflow integration patterns

It serves as the "integration test suite" for the workflow library itself.

## Architecture

```
stranske/Workflows (workflow library)
    │
    │ templates/integration-repo/ contains:
    │   - .github/workflows/ci.yml
    │   - pyproject.toml, src/, tests/
    │   - helper scripts (sync_*, resolve_*)
    │
    │ Auto-sync via maint-69-sync-integration-repo.yml
    ▼
This Repo (Workflows-Integration-Tests)
    ├── .github/workflows/ci.yml    → SYNCED from templates/integration-repo/
    ├── pyproject.toml              → SYNCED from templates/integration-repo/
    ├── src/example/                → SYNCED minimal implementation
    ├── tests/                      → LOCAL comprehensive test suite
    ├── scripts/                    → SYNCED stub implementations
    └── tools/                      → SYNCED stub implementations
```

## Files Overview

| File/Directory | Source | Purpose |
|----------------|--------|---------|
| `.github/workflows/ci.yml` | Synced from Workflows | Validates reusable CI workflow |
| `src/example/` | Synced from Workflows | Minimal implementation for testing |
| `tests/test_example.py` | Synced from Workflows | Basic smoke test |
| `tests/test_*.py` | Local (this chat) | Comprehensive coverage tests |
| `scripts/sync_*.py` | Synced from Workflows | Stub scripts called by reusable workflow |
| `tools/resolve_mypy_pin.py` | Synced from Workflows | Stub tool for mypy version resolution |
| `pyproject.toml` | Synced from Workflows | Minimal project config |
| `CLAUDE.md` | Local (this chat) | Development context (this file) |
| `.github/copilot-*` | Local (this chat) | Consumer repo development helpers |
| `.github/codex/` | Local (this chat) | Agent automation prompts |
| `config/coverage-baseline.json` | Local (this chat) | Coverage tracking |

## Development Workflow

### Testing Changes to Templates

When modifying `templates/integration-repo/` in Workflows:
1. Make changes in Workflows repo
2. Push to main branch
3. Sync workflow auto-triggers: `maint-69-sync-integration-repo.yml`
4. Changes appear in this repo
5. CI runs to validate changes work

### Local Development

This repo should have comprehensive tests for all scripts/tools even though they're stubs:

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test,dev]"

# Run tests with coverage
pytest --cov=src --cov=scripts --cov=tools --cov-report=term --cov-report=html

# Type checking
mypy src/ scripts/ tools/

# Code formatting
black src/ scripts/ tools/ tests/
```

## Test Coverage Goals

Even though scripts are stubs, they should have 100% coverage:
- `scripts/sync_test_dependencies.py` - All CLI argument combinations
- `scripts/sync_tool_versions.py` - All CLI argument combinations  
- `tools/resolve_mypy_pin.py` - Environment variable handling, GITHUB_OUTPUT writing
- `src/example/__init__.py` - Basic functionality

## Relationship to Consumer Repos

This repo demonstrates **minimal integration**. Real consumer repos like Travel-Plan-Permission or PAEM have:
- Full agent automation workflows
- Comprehensive keepalive systems
- Production code and tests
- Custom CI configurations

This repo validates that the **basic integration pattern works** before consumer repos adopt changes.

## Sync System

### Automatic Sync

Triggered by pushes to `templates/integration-repo/**` in Workflows:
- **Health Check**: `health-67-integration-sync-check.yml` validates sync status
- **Sync Workflow**: `maint-69-sync-integration-repo.yml` pushes template updates

### Manual Sync

```bash
# From Workflows repo
gh workflow run maint-69-sync-integration-repo.yml --repo stranske/Workflows

# Or with dry-run
gh workflow run maint-69-sync-integration-repo.yml --repo stranske/Workflows -f dry-run=true
```

## CI Workflow Details

The `ci.yml` workflow calls the reusable Python CI workflow:

```yaml
jobs:
  ci:
    uses: stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@v1
    with:
      python-version: '3.11'
    secrets: inherit
```

This validates:
- ✅ Workflow can be called from external repo
- ✅ Python matrix execution works
- ✅ Test execution succeeds
- ✅ Coverage reporting works
- ✅ Helper scripts integrate correctly

## Debugging Sync Issues

If templates aren't syncing:

```bash
# Check last sync workflow run
gh run list --workflow=maint-69-sync-integration-repo.yml --repo stranske/Workflows --limit 5

# Check health workflow for detected drift
gh run list --workflow=health-67-integration-sync-check.yml --repo stranske/Workflows --limit 5

# Compare local files with templates
diff .github/workflows/ci.yml <(cat /workspaces/Workflows/templates/integration-repo/.github/workflows/ci.yml)
```

## Common Patterns

### Adding New Test Coverage

When adding tests (like in this chat session):
1. Tests live in `tests/` and are NOT synced from Workflows
2. Test files use pytest conventions: `test_*.py`
3. Aim for 100% coverage of all scripts/tools
4. Tests should validate behavior, not just achieve coverage

### Updating Synced Files

DO NOT edit files that are synced from Workflows:
- `.github/workflows/ci.yml`
- `src/example/__init__.py`
- `tests/test_example.py`
- `scripts/sync_*.py`
- `tools/resolve_mypy_pin.py`
- `pyproject.toml` (except for dev dependencies)

These will be overwritten on next sync.

## Development Tools

This repo now includes consumer repo development elements:
- `.github/copilot-instructions.md` - GitHub Copilot context
- `.github/copilot-skills/` - Skill-specific Copilot guidance
- `.github/codex/` - Agent automation prompts
- `config/coverage-baseline.json` - Coverage tracking baseline

These help make development easier and provide examples for other consumer repos.

---

**Next Steps**: Run comprehensive test suite to validate coverage, then commit all changes to a feature branch.
