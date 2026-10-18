# Synced workspace validation (2026-10-18)

First Mac → desktop sync using `deployment/sync_desktop.py`, targeting
`D:\cs427-workspace` on `PC-20230218RALO`.

| Item | Value |
| --- | --- |
| Mac commit | `f6be9e6cdc53e1dbd07d41422389d43c1bb925e2` |
| `source.sha256` | `d749159289a12ed3d4388a0f92937373618f992d859397b6090cea5f209b0b84` |
| Source files | 82 |
| Archive files | 1022 (2.5 MB compressed) |
| `checks` | 285 passed, 9 deselected, 20.92 s |
| `slow-checks` | 9 passed, 24 deselected, 35.06 s |
| Ruff | All checks passed |

The desktop copy keeps `experiments/` and `desktop_validation/` across syncs; only
the code directories (`src/`, `tests/`, `deployment/`, `SWE-bench/`, `docs/`) are
replaced. `D:\cs427-upgrade-20261017` remains the historical experiment copy and was
not modified.

The Mac full non-slow suite is 509 passed / 18 skipped; desktop `checks` is the
scoped 285-test set used by `deployment/desktop_run.py`, not the full suite.

Logs: [pytest.log](pytest.log), [pytest_slow.log](pytest_slow.log),
[ruff.log](ruff.log), [sync_manifest.json](sync_manifest.json).
