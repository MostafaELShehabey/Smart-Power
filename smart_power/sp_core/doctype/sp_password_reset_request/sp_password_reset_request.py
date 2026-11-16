"""A user's Forgot password request, handled by the admin (SP-36): there is no self-service email."""

from frappe.model.document import Document


class SPPasswordResetRequest(Document):
	pass
