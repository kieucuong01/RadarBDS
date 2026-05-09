---
paths:
  - "tests/sanity_test.py"
---

# Testing & Quality Assurance

## Mandatory Sanity Check
Before finishing any task that involves backend logic, database schema changes, or API updates, you MUST run the sanity test suite:

```bash
python tests/sanity_test.py
```

### What is covered:
1. **API Stability**: Ensures endpoints return 200 and valid JSON.
2. **Filtering Logic**: Verifies that MOS (Ngợp), Property Types, and Wards correctly filter data.
3. **Sorting**: Confirms data is ordered as requested (Price, Date, etc.).
4. **Serialization**: Checks that all database objects are converted to dicts (prevents 500 errors).

## Regression Prevention
- If a test fails, DO NOT ignore it. Fix the code until all tests pass.
- If you add a new API endpoint or a major feature, add a corresponding test case to `tests/sanity_test.py`.

## Token Saving Tip
- Run the tests locally to verify logic before asking the user to check the UI. This reduces unnecessary interaction cycles and saves tokens.
