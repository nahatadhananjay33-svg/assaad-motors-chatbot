# Tests

Test suites are co-located with the production modules they test:

- `app/inventory_system/*_tests.py` — chat API, parser/retrieval routing,
  FAQ, lead capture, analytics, media, inventory loader/sync, hardening
  (run with `python -m unittest <module> ...` from `app/inventory_system/`)
- `app/media_sync/media_sync_tests.py`
- `app/media_sync_poc/media_sync_poc_tests.py`

## Why tests aren't physically separated into this folder

`inventory_system`'s modules use flat, same-directory imports
(`from chat_service import ChatService`, etc.) rather than package-relative
imports. Splitting `*_tests.py` out into a top-level `/tests` folder would
require either adding `sys.path` shims to every test file or converting the
codebase to a proper package layout — both are behavior/import changes beyond
the scope of this deployment-packaging pass ("do not change imports unless
files are physically moved and imports must be updated", and moving the test
files alone would force exactly that).

Keeping tests next to the code they test is also the lower-risk choice for a
no-git repo: it required zero import edits and the full regression suite
passes unchanged after the reorg (see `deployment_package_report.md`).

## Regression suite

```bash
cd app/inventory_system
python -m unittest faq_tests inventory_retrieval_tests analytics_tests \
    lead_tests chat_api_tests inventory_loader_tests inventory_sync_tests \
    media_tests media_loader_tests media_api_tests router_tests hardening_tests
```
