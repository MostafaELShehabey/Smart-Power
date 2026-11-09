#!/usr/bin/env python3
"""CI check: every user-facing string in the app has an Arabic translation (tech plan section 12).

Collects DocType names, field labels, descriptions and Select options from the DocType JSON,
role and role profile names from the fixtures, and _("...") strings from Python, JS and
HTML, then checks them against smart_power/translations/ar.csv.

    python scripts/check_translations.py            # fails with the missing strings
    python scripts/check_translations.py --missing  # prints them as CSV lines to fill in
"""

import ast
import csv
import glob
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smart_power")
CSV_PATH = os.path.join(ROOT, "translations", "ar.csv")
SKIP_FIELDTYPES = {"Column Break", "Tab Break"}
JS_HTML_RE = re.compile(r"""__\(\s*(['"])(.+?)\1|_\(\s*(['"])(.+?)\3\s*\)""")


def doctype_strings() -> set[str]:
	out = set()
	for path in glob.glob(os.path.join(ROOT, "*", "doctype", "*", "*.json")):
		with open(path, encoding="utf-8") as f:
			d = json.load(f)
		if d.get("doctype") != "DocType":
			continue
		out.add(d["name"])
		for df in d.get("fields", []):
			if df.get("fieldtype") in SKIP_FIELDTYPES:
				continue
			for key in ("label", "description"):
				if df.get(key):
					out.add(df[key])
			if df.get("fieldtype") == "Select" and df.get("options"):
				out.update(o for o in df["options"].split("\n") if o.strip())
	return out


def fixture_strings() -> set[str]:
	out = set()
	path = os.path.join(ROOT, "fixtures", "role.json")
	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			out.update(r["name"] for r in json.load(f))
	# role profiles come from the catalogue, not from fixtures
	catalogue = os.path.join(ROOT, "sp_core", "setup", "role_catalogue.py")
	with open(catalogue, encoding="utf-8") as f:
		out.update(re.findall(r'ProfileDef\(\s*"([^"]+)"', f.read()))
	path = os.path.join(ROOT, "fixtures", "custom_field.json")
	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			for r in json.load(f):
				for key in ("label", "description"):
					if r.get(key):
						out.add(r[key])
				if r.get("fieldtype") == "Select" and r.get("options"):
					out.update(o for o in r["options"].split("\n") if o.strip())
	return out


def code_strings() -> set[str]:
	out = set()
	for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
		if "/tests/" in path or "/devtools/" in path or os.path.basename(path).startswith("test_"):
			continue
		with open(path, encoding="utf-8") as f:
			tree = ast.parse(f.read())
		for node in ast.walk(tree):
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "rule":
				for kw in node.keywords:
					if kw.arg in ("title", "description") and isinstance(kw.value, ast.Constant):
						out.add(kw.value.value)
			if (
				isinstance(node, ast.Call)
				and isinstance(node.func, ast.Name)
				and node.func.id == "_"
				and node.args
				and isinstance(node.args[0], ast.Constant)
				and isinstance(node.args[0].value, str)
			):
				out.add(node.args[0].value)
	for path in glob.glob(os.path.join(ROOT, "**", "*.js"), recursive=True) + glob.glob(
		os.path.join(ROOT, "**", "*.html"), recursive=True
	):
		if "/dist/" in path or "node_modules" in path:
			continue
		with open(path, encoding="utf-8") as f:
			for m in JS_HTML_RE.finditer(f.read()):
				out.add(m.group(2) or m.group(4))
	return out


def translated() -> set[str]:
	if not os.path.exists(CSV_PATH):
		return set()
	with open(CSV_PATH, encoding="utf-8") as f:
		return {row[0] for row in csv.reader(f) if row and len(row) >= 2 and row[1].strip()}


def main() -> int:
	needed = doctype_strings() | fixture_strings() | code_strings()
	missing = sorted(s for s in needed - translated() if not s.isdigit())
	if "--missing" in sys.argv:
		w = csv.writer(sys.stdout, lineterminator="\n")
		for s in missing:
			w.writerow([s, ""])
		return 0
	if missing:
		print(f"{len(missing)} strings have no Arabic translation in translations/ar.csv:")
		for s in missing:
			print("  " + s)
		return 1
	print(f"translations: all {len(needed)} strings translated")
	return 0


if __name__ == "__main__":
	sys.exit(main())
