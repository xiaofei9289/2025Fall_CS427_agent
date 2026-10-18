# SWE-bench run audit

Run: `deliverables_final/generations`

Predictions: 50; trajectories: 50; graded tasks: 50; resolved: 25.

The grading reports define outcomes. Trajectory symptoms are review leads, not proven root causes. Metrics from mismatched or missing trajectories cannot explain the submitted patch's outcome.

Integrity issues: `{}`

Step limits: `{"100": 4, "250": 3, "50": 43}`

Memory: `{"False": 50}`

| Task | Grading | Category | Integrity issues | Observed symptoms |
|---|---|---|---|---|
| django__django-10880 | resolved | resolved | - | path_error |
| django__django-11095 | resolved | resolved | - | - |
| django__django-11265 | resolved | resolved | - | path_error, test_failure |
| django__django-11333 | unresolved | unresolved_requires_review | - | - |
| django__django-11532 | resolved | resolved | - | - |
| django__django-11880 | resolved | resolved | - | path_error |
| django__django-13089 | resolved | resolved | - | action_format_error, path_error |
| django__django-13363 | resolved | resolved | - | - |
| django__django-13417 | unresolved | unresolved_requires_review | - | path_error |
| django__django-14007 | empty_patch | budget_exhausted | - | path_error |
| django__django-14017 | unresolved | unresolved_requires_review | - | path_error |
| django__django-14725 | unresolved | unresolved_requires_review | - | path_error, action_format_error |
| django__django-14855 | resolved | resolved | - | path_error |
| django__django-15103 | unresolved | unresolved_requires_review | - | - |
| django__django-15280 | empty_patch | empty_submission | - | path_error |
| django__django-15315 | resolved | resolved | - | path_error |
| django__django-15368 | resolved | resolved | - | environment_error |
| django__django-15554 | unresolved | unresolved_requires_review | - | path_error |
| django__django-15863 | resolved | resolved | - | path_error, action_format_error |
| django__django-15987 | resolved | resolved | - | - |
| django__django-16136 | resolved | resolved | - | test_failure |
| django__django-16560 | unresolved | unresolved_requires_review | - | tool_argument_error, action_format_error, path_error |
| django__django-16642 | resolved | resolved | - | path_error, tool_argument_error, action_format_error |
| django__django-16661 | resolved | resolved | - | path_error |
| matplotlib__matplotlib-20826 | unresolved | unresolved_requires_review | - | path_error |
| matplotlib__matplotlib-23299 | unresolved | unresolved_requires_review | - | tool_argument_error, action_format_error, test_failure |
| matplotlib__matplotlib-24870 | unresolved | unresolved_requires_review | - | path_error |
| matplotlib__matplotlib-25332 | unresolved | unresolved_requires_review | - | path_error |
| psf__requests-2317 | unresolved | unresolved_requires_review | - | environment_error |
| pydata__xarray-6461 | empty_patch | budget_exhausted | - | environment_error, path_error |
| pydata__xarray-6744 | unresolved | unresolved_requires_review | - | action_format_error, path_error |
| pydata__xarray-6992 | unresolved | unresolved_requires_review | - | - |
| pylint-dev__pylint-4604 | unresolved | unresolved_requires_review | - | path_error, action_format_error |
| pylint-dev__pylint-4661 | unresolved | unresolved_requires_review | - | path_error |
| pytest-dev__pytest-5809 | resolved | resolved | - | - |
| pytest-dev__pytest-7982 | resolved | resolved | - | path_error |
| scikit-learn__scikit-learn-13135 | resolved | resolved | - | path_error |
| scikit-learn__scikit-learn-13142 | resolved | resolved | - | path_error |
| sphinx-doc__sphinx-8595 | unresolved | unresolved_requires_review | - | path_error, environment_error |
| sphinx-doc__sphinx-8721 | resolved | resolved | - | path_error |
| sphinx-doc__sphinx-9229 | empty_patch | empty_submission | - | tool_argument_error, action_format_error, path_error |
| sympy__sympy-13615 | unresolved | unresolved_requires_review | - | path_error, test_failure |
| sympy__sympy-13852 | unresolved | unresolved_requires_review | - | path_error, tool_argument_error, action_format_error, test_failure |
| sympy__sympy-14248 | empty_patch | budget_exhausted | - | path_error, environment_error |
| sympy__sympy-14531 | resolved | resolved | - | path_error |
| sympy__sympy-15017 | resolved | resolved | - | path_error |
| sympy__sympy-16792 | resolved | resolved | - | path_error, environment_error |
| sympy__sympy-17139 | resolved | resolved | - | - |
| sympy__sympy-19346 | resolved | resolved | - | - |
| sympy__sympy-22080 | empty_patch | budget_exhausted | - | path_error, tool_argument_error, action_format_error |
