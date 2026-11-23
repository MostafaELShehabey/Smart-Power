// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Every active user, their guide and whether their training is complete (SP-162).
frappe.query_reports["SP Training Status"] = {
	filters: [{ fieldname: "only_open", label: __("Only Not Completed"), fieldtype: "Check", default: 0 }],
};
