#!/usr/bin/env python3
"""CI check: the shipped fixtures hold developer-owned records only (SP-164).

- Custom Field and Property Setter records belong to an SP module, never to "Smart Power Admin".
- Custom Field names start with sp_ (the admin's fields get Frappe's custom_ prefix).
- Role, Role Profile and Workflow records are named "SP ...".
- No record appears twice.
"""

import glob
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smart_power")
sys.path.insert(0, os.path.join(ROOT, ".."))

from smart_power.constants import DEV_FIELD_PREFIX, DEV_NAME_PREFIX, SP_MODULES

MODULE_OWNED = {"Custom Field", "Property Setter", "Print Format", "Notification"}
PREFIX_OWNED = {"Role", "Role Profile", "Workflow"}


def main() -> int:
	problems, seen = [], set()
	for path in sorted(glob.glob(os.path.join(ROOT, "fixtures", "*.json"))):
		with open(path, encoding="utf-8") as f:
			records = json.load(f)
		for rec in records:
			dt, name = rec.get("doctype"), rec.get("name")
			key = (dt, name)
			if key in seen:
				problems.append(f"{dt} {name}: listed twice")
			seen.add(key)
			if dt in MODULE_OWNED and rec.get("module") not in SP_MODULES:
				problems.append(f"{dt} {name}: module {rec.get('module')!r} is not a developer module")
			if dt == "Custom Field" and not (rec.get("fieldname") or "").startswith(DEV_FIELD_PREFIX):
				problems.append(f"{dt} {name}: developer fields must start with {DEV_FIELD_PREFIX}")
			if dt in PREFIX_OWNED and not (name or "").startswith(DEV_NAME_PREFIX):
				problems.append(f"{dt} {name}: developer records must be named '{DEV_NAME_PREFIX}...'")
	if problems:
		print("Fixture ownership problems:")
		print("\n".join("  " + p for p in problems))
		return 1
	print(f"fixtures: {len(seen)} developer-owned records, no admin records")
	return 0


if __name__ == "__main__":
	sys.exit(main())
