## Smart Power ERP (`smart_power`)

The custom Frappe app for Smart Power, a solar energy and power systems company. It runs on
Frappe v16 and ERPNext v16, unchanged: every Smart Power change lives in this app.

The design is in the technical implementation plan (Claude doc, 6-11-2026), the Miro board
"Smart Power" (frames 01–05, ERDs 7.1–7.6) and Jira project SP.

### Rules that keep the build clean

1. **Never edit Frappe or ERPNext.** Custom fields, property setters, roles and workflows ship as
   fixtures; behaviour goes through `doc_events`.
2. **Numbers are data.** Business values live in Smart Power Settings, SP Rule Setting or the
   calculation templates, never in code. `scripts/check_numeric_literals.py` fails a PR that adds
   one. Seed values are in `smart_power/sp_core/setup/defaults.json`, each with its source.
3. **Developer and admin own different records** (SP-164). See [docs/fixtures-runbook.md](docs/fixtures-runbook.md).
4. **Every label has an Arabic translation** in `smart_power/translations/ar.csv`.

### Layout

| Path | What it holds |
|---|---|
| `smart_power/sp_core` | Settings, rules, review centre, logs, task inbox, lists, roles and locale setup |
| `smart_power/sp_sales`, `sp_quotes`, `sp_stations`, `sp_stock`, `sp_finance`, `sp_winch`, `sp_site` | One Frappe module per area (filled from S1 on). Purchasing sits in `sp_stock`, the showroom cash box in `sp_finance` |
| `smart_power/rules` | The rules engine (`run(doc, event)`) and the rule functions |
| `smart_power/api/mobile/v1` | Mobile API (Release 2) |
| `smart_power/devtools` | Fixture preflight, admin backup, post-install check |
| `smart_power/fixtures` | Developer-owned roles and custom fields (role profiles are synced from `sp_core/setup/role_catalogue.py`) |
| `scripts/` | CI checks |

Business logic goes in plain Python services that can be tested without the UI; DocType
controllers stay thin.

### What S0 delivers

- **SP-19 / SP-164:** app skeleton, eight modules, fixtures filtered to developer records, the
  "Smart Power Admin" module for the admin's own changes, a pre-migrate check that stops a
  deploy that would overwrite them, and a nightly JSON backup of them.
- **SP-128:** Smart Power Settings (with margin ranges, brand priority and the account map),
  SP Rule Setting with Off / Warn / Block, SP Rule Hit, SP Rule Override Log and SP Review Item.
  First rules: the total-discount limit per role and the quote validity.
- **SP-34:** the 36 role keys from the Miro catalogue, one role profile per person type, the User
  custom fields, a CSV-driven user seed, and the redirect that sends drivers to the field page.
- **SP-22 (part):** Arabic, Egypt, EGP, DD-MM-YYYY, Africa/Cairo, Saturday as the first day,
  fiscal year 2027, the self-hosted IBM Plex Sans Arabic font, the navy and gold theme, the logo.
- **SP-20 (part):** CI with lint, semgrep, the project checks, a fresh install and the tests.
- Also: the append-only SP Audit Log and SP Edit Reason Log, the SP Task inbox and SP List Value.

### Developer setup

Requirements: Python 3.14, Node 24, MariaDB 11.8, Redis, and `frappe-bench`.

```bash
bench init frappe-bench --frappe-branch v16.55.2 --python python3.14
cd frappe-bench
bench get-app https://github.com/frappe/erpnext --branch v16.54.0
bench get-app smart_power <this repo>
bench new-site sp.localhost --install-app erpnext --install-app smart_power
bench --site sp.localhost set-config developer_mode 1
```

**The tests have their own site.** Never set `allow_tests` on a working site (the one you open in
the browser, staging, production):

```bash
bench new-site test_sp --install-app erpnext --install-app smart_power
bench --site test_sp set-config allow_tests true
bench --site test_sp run-tests --app smart_power
```

The tests load ERPNext's test data: about twenty test companies with their accounts, users, items
and warehouses, and System Settings set to English and Asia/Kolkata. On a working site these mix
with Smart Power's records (test users in pickers, accounts listed twice) and move every time by
3.5 hours. The test helpers stop with a clear message on a site whose name does not start with
`test_` (BUG-39).

If the tests already ran on a working site, `bench --site <site> execute
smart_power.sp_core.setup.locale.apply_locale` puts the language and the time zone back for new
records; the test records and the times already stored stay, so a site meant for real data is
better created again.

Before a commit: `pre-commit install` once, then the hooks run ruff, eslint and the three
project checks.

### Seeding the users (cutover)

Fill a copy of `smart_power/sp_core/setup/users_seed_template.csv` with each person's email and
mobile, then run:

```bash
bench --site <site> execute smart_power.sp_core.setup.users.seed_users --kwargs "{'path': '/path/users.csv'}"
```

### Branches and commits

- `main` is production, `develop` is staging, features are `feature/SP-123-short-name`.
- Commit messages start with the Jira key: `SP-123: message`.
- Every PR names its Jira key, gets one review and must pass CI. Releases are tagged `r1.0`, `r1.1`…

### License

Proprietary. All rights reserved by Smart Power.
