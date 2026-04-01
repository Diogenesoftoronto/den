# Property Test Troubleshooting

This page helps diagnose and fix failures in `uv run pytest tests/python`.

## Common failure patterns

## 1. Flaky failures

Symptoms:
- Test fails intermittently
- Re-running passes without code changes

Actions:
1. Re-run with a fixed seed:
   ```bash
   uv run pytest tests/python -k <test_name> --hypothesis-seed=1
   ```
2. Disable deadline pressure if timing-sensitive behavior is expected.
3. Remove hidden state from tested functions.
4. Ensure tests do not depend on dict insertion order unless explicitly sorted.

## 2. Unexpected shrinking output

Symptoms:
- Failure report shows a tiny/minimal input that looks unrealistic

Explanation:
- Hypothesis shrinks to the smallest counterexample by design.

Actions:
1. Reproduce with seed + failing example.
2. Add explicit assumptions only when truly required.
3. Tighten strategies to valid input domain when test intent requires it.

## 3. Robustness test fails on malformed payloads

Symptoms:
- Exceptions raised from parser functions (for example in `extract_den_peers`)

Actions:
1. Confirm parser accepts `Mapping[str, object]` and defends type boundaries.
2. Guard every nested read with `isinstance(...)` checks.
3. Return safe defaults instead of raising for malformed external JSON.

## 4. Invariant regression failures

Symptoms:
- Round-trip or idempotence tests fail after feature change

Actions:
1. Decide if behavior change is intentional.
2. If intentional, update invariant documentation and tests together.
3. If not intentional, restore prior invariant in `core.py`.

## 5. Slow property test suite

Actions:
1. Focus strategies to realistic domains.
2. Split heavy tests into separate files.
3. Run targeted tests during iteration:
   ```bash
   uv run pytest tests/python -k <keyword>
   ```

## Reproduce exactly what CI runs

```bash
uv run mypy src
uv run pytest tests/python
bash tests/test-den.sh --no-build
```

## Debug commands

Run one test with detailed output:

```bash
uv run pytest tests/python/test_core_properties.py -k <test_name> -vv
```

Keep and inspect latest generated examples:

```bash
ls -la .hypothesis
```

Clean local hypothesis cache if needed:

```bash
rm -rf .hypothesis
```

## When to rewrite a property test

Rewrite if the test is asserting implementation details instead of behavior.

Keep the test if it captures a stable external contract users rely on.
