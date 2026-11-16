"""SP-35's read rules on ERPNext's Quotation (extend_doctype_class): cost, profit and hidden lines
for the quote's creator and the admin only; hidden lines are never printed (SP-58)."""

from smart_power.permissions import strip_quote_internals


class SPQuotation:
	"""Mixed in ahead of ERPNext's Quotation, so super() is ERPNext's own method."""

	def apply_fieldlevel_read_permissions(self):
		"""Used by the form, REST and get_quote_view before the quote leaves the server."""
		super().apply_fieldlevel_read_permissions()
		strip_quote_internals(self)

	def before_print(self, settings=None):
		super().before_print(settings)
		self.set("items", [row for row in self.items if not row.get("sp_is_hidden")])
		strip_quote_internals(self)
