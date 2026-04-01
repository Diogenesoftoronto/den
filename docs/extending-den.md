# Extending den

This guide explains how to add functionality safely.

## Architecture

- CLI surface: `src/den_cli/cli.py`
- MCP server: `src/den_cli/mcp_server.py`
- Reusable pure logic: `src/den_cli/core.py`
- Property tests: `tests/python/test_core_properties.py`
- CLI integration tests: `tests/python/test_cli_commands.py`
- Antithesis workload: `tests/antithesis/test_core_properties.py`
- Integration smoke tests: `tests/test-den.sh`

## Add a new command

1. Add a Typer command function in `src/den_cli/cli.py`.
2. Keep orchestration code minimal in the command function.
3. Move reusable, pure transformations/invariants into `src/den_cli/core.py`.
4. Add unit/property tests for core behavior.
5. Add a smoke assertion in `tests/test-den.sh` only if needed.

Example command skeleton:

```python
@app.command()
def status(name: Annotated[str, typer.Argument(help="Den name")]) -> None:
    den_name = normalize_den_name(name)
    # call external tools via _run_checked(...)
```

## Design rules for new functionality

- Normalize names once at command boundaries (`normalize_den_name`).
- Use `_run_checked(...)` for every external command that must succeed.
- Prefer typed pure functions in `core.py` for parsing/selection logic.
- Keep side effects (shelling out, prompts) in `cli.py`.
- Preserve non-zero exits for operational failures.

## Add new property tests

Good targets:
- idempotence (`f(f(x)) == f(x)`)
- round-trip invariants
- ordering invariants
- malformed input robustness
- equivalence to a simple reference model

Template:

```python
@given(st.text(min_size=1))
def test_my_invariant(value: str) -> None:
    result = my_function(value)
    assert some_property(result)
```

## Required validation before commit

```bash
uv run mypy src
uv run pytest tests/python
bash tests/test-den.sh --no-build
```

Run full container validation when touching Docker/bootstrap/entrypoint paths:

```bash
bash tests/test-den.sh
```
