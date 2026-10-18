# Retrieval attribution audit

Run: `experiments/gate-20261017/retrieval`
Tasks: 5; gold in top-10: 5; read gold: 5; edited gold: 4; resolved: 3.

| Instance | Resolved | Gold rank | Read gold | Edited gold | Class | Steps | Search query |
| --- | --- | ---: | --- | --- | --- | ---: | --- |
| django__django-11333 | True | 1 | True | True | `resolved` | 14 | get_resolver URLResolver lru_cache set_urlconf get_urlconf |
| django__django-11532 | False | 1 | True | True | `edited_not_resolved` | 19 | mail message Message-ID DNS_NAME make_msgid forbid_multi_line_headers |
| django__django-14855 | True | 1 | True | True | `resolved` | 11 | get_admin_url reverse readonly field custom admin site |
| django__django-15315 | True | 1 | True | True | `resolved` | 12 | Field __hash__ immutable model field hash |
| matplotlib__matplotlib-20826 | False | 3 | True | False | `read_not_edited` | 50 | clear axes ticks tick labels shared axis visibility |

## Classification counts

- `edited_not_resolved`: 1
- `read_not_edited`: 1
- `resolved`: 3
