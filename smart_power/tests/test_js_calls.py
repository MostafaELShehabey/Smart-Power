"""Every server method the app's JavaScript calls exists and is whitelisted.

A method without @frappe.whitelist() still passes a test that imports it in Python, and fails
only in the browser ("+ New" was dead this way after SP-131). This reads the calls out of the
JavaScript itself: frappe.call / frappe.xcall with the method written out, or built from a
constant of the same file (`${API}.method`, the nearest one defined above the call).
"""

import re
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

APP = "smart_power"
BUILT = ("dist", "node_modules")
CALL = re.compile(r"""frappe\.x?call\(\s*(?:\{\s*method\s*:\s*)?([`"'])(.*?)\1""")
CONSTANT = re.compile(rf"""(?:(?:const|let|var)\s+(\w+)\s*=|(\w+)\s*:)\s*["']({APP}[\w.]*)["']""")
FROM_CONSTANT = re.compile(r"\$\{(?:this\.)?(\w+)\}((?:\.\w+)+)$")


def called_methods() -> dict[str, set[str]]:
	"""method path → the JavaScript files that call it."""
	root = Path(frappe.get_app_path(APP))
	found: dict[str, set[str]] = {}
	for path in root.rglob("*.js"):
		if set(path.parts) & set(BUILT):
			continue
		source = path.read_text(encoding="utf-8")
		constants = [(m.start(), m.group(1) or m.group(2), m.group(3)) for m in CONSTANT.finditer(source)]
		for call in CALL.finditer(source):
			method = call.group(2)
			built = FROM_CONSTANT.match(method)
			if built:
				above = [
					value for at, name, value in constants if name == built.group(1) and at < call.start()
				]
				if not above:
					continue
				method = above[-1] + built.group(2)
			if method.startswith(f"{APP}.") and "$" not in method:
				found.setdefault(method, set()).add(str(path.relative_to(root)))
	return found


class TestJavaScriptCalls(IntegrationTestCase):
	def test_every_method_the_javascript_calls_is_whitelisted(self):
		methods = called_methods()
		self.assertTrue(methods, "no calls found: the scan itself is broken")
		problems = []
		for method, files in sorted(methods.items()):
			try:
				function = frappe.get_attr(method)
			except (ImportError, AttributeError):
				problems.append(f"{method} does not exist (called from {', '.join(sorted(files))})")
				continue
			if function not in frappe.whitelisted:
				problems.append(f"{method} is not whitelisted (called from {', '.join(sorted(files))})")
		self.assertEqual(problems, [])

	def test_the_scan_reads_the_dock_calls(self):
		# the calls that broke: written as `${this.API}.name` in sp_shell.js
		methods = called_methods()
		for name in ("get_new_menu", "get_counts"):
			self.assertIn("public/js/sp_shell.js", methods.get(f"{APP}.shell.{name}", set()))
