#!/usr/bin/env python3
"""CI check: no business numbers in Python or JavaScript (tech plan section 1).

Numbers are data: they live in Smart Power Settings, SP Rule Setting, CalcTemplate or the
defaults fixtures. This check fails on numeric literals in app code other than 0, 1, -1
and 100 (percent). A line can opt out with a comment that says why:

    TIMEOUT = 30  # sp-allow-number: HTTP timeout, not a business value

Tests, patches, devtools and JSON files are not checked.
"""

import ast
import glob
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smart_power")
ALLOWED = {0, 1, -1, 100}
PRAGMA = "sp-allow-number"
SKIP_DIRS = ("/tests/", "/patches/", "/devtools/", "/public/dist/", "/node_modules/")
JS_NUMBER = re.compile(r"(?<![\w.$#'\"-])(\d+(?:\.\d+)?)(?![\w.%'\"])")


def skipped(path: str) -> bool:
	return any(d in path for d in SKIP_DIRS) or os.path.basename(path).startswith("test_")


class Visitor(ast.NodeVisitor):
	def __init__(self):
		self.hits: list[tuple[int, object]] = []
		self._docstrings: set[int] = set()

	def visit_Constant(self, node: ast.Constant):
		value = node.value
		if isinstance(value, bool) or not isinstance(value, int | float):
			return
		if value in ALLOWED:
			return
		self.hits.append((node.lineno, value))

	def visit_UnaryOp(self, node: ast.UnaryOp):
		if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
			value = node.operand.value
			if isinstance(value, int | float) and not isinstance(value, bool) and -value in ALLOWED:
				return
		self.generic_visit(node)

	def visit_Subscript(self, node: ast.Subscript):
		# indexes and slices such as row[2] or parts[:3] are positions, not business values
		self.visit(node.value)


def check_python(path: str) -> list[str]:
	with open(path, encoding="utf-8") as f:
		source = f.read()
	lines = source.splitlines()
	v = Visitor()
	v.visit(ast.parse(source))
	return [
		f"{path}:{line}: numeric literal {value}" for line, value in v.hits if PRAGMA not in lines[line - 1]
	]


def check_js(path: str) -> list[str]:
	out = []
	with open(path, encoding="utf-8") as f:
		for i, line in enumerate(f, 1):
			code = line.split("//", 1)[0]
			if PRAGMA in line:
				continue
			for m in JS_NUMBER.finditer(code):
				if float(m.group(1)) not in ALLOWED:
					out.append(f"{path}:{i}: numeric literal {m.group(1)}")
	return out


def main() -> int:
	problems = []
	for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True)):
		if not skipped(path):
			problems += check_python(path)
	for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.js"), recursive=True)):
		if not skipped(path):
			problems += check_js(path)
	if problems:
		print("Business numbers belong in settings, rules or templates, not in code:")
		print("\n".join("  " + os.path.relpath(p, os.path.dirname(ROOT)) for p in problems))
		return 1
	print("numeric literals: clean")
	return 0


if __name__ == "__main__":
	sys.exit(main())
