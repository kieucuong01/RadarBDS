# Development Commands

Use UTF-8 mode on Windows because the project contains Vietnamese text.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 -m pytest tests
& $py -X utf8 tests\test_valuation.py
& $py -X utf8 tests\test_feature_extractor.py
& $py -X utf8 tests\test_dedup.py
& $py -X utf8 tests\test_lifecycle.py
& $py -X utf8 -m py_compile app.py radar.py db\connection.py db\schema.py db\raw_listings.py db\listings.py db\crawl_runs.py db\analytics.py db\sqlite.py config\database_sqlite.py cleansing\reprocess.py cleansing\normalizer.py cleansing\feature_extractor.py analytics\valuation.py services\market_data.py cli\crawlers.py cli\system.py
```

If `pytest` is missing, install dev dependencies first or run the direct smoke-test files above.
`tests\test_guland.py` and `tests\sanity_test.py` are integration checks and are intentionally not part of the default pytest set.

Routine app commands:

```powershell
& $py -X utf8 radar.py inspect
& $py -X utf8 radar.py reprocess
& $py -X utf8 app.py
```
