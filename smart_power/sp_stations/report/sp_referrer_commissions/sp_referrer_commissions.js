// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Referrer commissions (SP-177): agreed, posted, paid and owed per referrer.
frappe.query_reports["SP Referrer Commissions"] = {
	filters: [{ fieldname: "referrer", label: __("Referrer"), fieldtype: "Link", options: "Sales Partner" }],
};
