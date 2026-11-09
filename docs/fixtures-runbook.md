# Fixture ownership runbook (SP-164)

Two people change this system: the developer, through releases, and the admin (Mohamed), through
Frappe's no-code tools. Each owns different records, so a deploy never overwrites the admin's work.

## Who owns what

| Record | Developer owns | Admin owns |
|---|---|---|
| Custom Field | module in an `SP …` module and fieldname `sp_…` | module "Smart Power Admin" (set automatically), fieldname `custom_…` |
| Property Setter, Print Format, Notification, Client Script, Server Script, Report | module in an `SP …` module | module "Smart Power Admin" (set automatically when created outside developer mode) |
| Role, Role Profile, Workflow | name starts with `SP ` | any other name (the `SP ` prefix is refused) |
| Settings values, rule levels and limits, list values | seeded once on install | everything after install |

Only developer-owned records are exported (`hooks.py` → `fixtures`) and synced on deploy.

## What protects the admin's changes

1. **Tagging:** a record the admin creates with Customize Form, Print Format Builder, Notification
   and the other tools gets the module "Smart Power Admin". The `sp_` field prefix, the SP modules
   and `SP ` names are refused outside developer mode.
2. **Preflight:** before every migrate, `smart_power.devtools.fixtures.preflight` compares the
   fixtures with the site. If a fixture would overwrite an admin-owned record, the deploy stops
   with the list of conflicts. Nothing has been changed at that point.
3. **Drift report:** if the admin edited a developer record in place (for example the label of an
   `sp_` field), the preflight prints a "drift" line. The deploy restores the shipped version.
4. **Nightly backup:** `smart_power.tasks.backup_admin_customizations` saves every admin-owned
   customization as a private JSON file (`sp-admin-customizations-YYYY-MM-DD.json`, folder Home).
5. **CI:** `scripts/check_fixtures.py` fails a PR whose fixtures hold anything but developer records.

## When the preflight stops a deploy

1. Read the conflict list in the deploy log.
2. Either rename the developer record in the branch (a new `sp_` fieldname or `SP ` name), or
   promote the admin's record (below) and drop the developer copy.
3. Deploy again.

## Promote an admin change into code

Use this when the admin built something the developer must now own (for example a field that a
report or rule depends on).

1. On staging, open the record and set its module to the right `SP …` module. For a custom field,
   create a new `sp_` field with the same settings and move the data with a patch; the admin's
   `custom_` field is then hidden or removed by the admin.
2. `bench --site <staging> export-fixtures --app smart_power`, commit, open a PR.
3. After the release, tell the admin the record is now developer-owned: later edits must go
   through a change request.

## When the admin wants to change a developer record

Developer records are recognised by the `sp_` or `SP ` prefix. An in-place edit is reverted by the
next deploy (and reported as drift). Instead:

- Clone the role profile or workflow under a new name without the `SP ` prefix, or
- Ask for the change in Jira so it ships in the next release.
