// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Calibration report (SP-183): each template line's estimate at the deposit against what the
// closed stations used and cost, with a suggested default. "Create Draft Version" copies the
// template with the suggestions, unpublished, for the admin to review.
frappe.query_reports["SP Template Calibration"] = {
	filters: [
		{
			fieldname: "template",
			label: __("Calculation Template"),
			fieldtype: "Link",
			options: "SP Calc Template",
			reqd: 1,
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],
	onload(report) {
		report.page.add_inner_button(__("Create Draft Version"), async () => {
			const { template, from_date, to_date } = report.get_values() || {};
			if (!template) return;
			const { message } = await frappe.call({
				method: "smart_power.sp_quotes.calibration.create_draft",
				args: { template, from_date, to_date },
				freeze: true,
			});
			frappe.show_alert({ message: __("Draft version {0} made with the suggested defaults.", [message]), indicator: "green" });
			frappe.set_route("Form", "SP Calc Template", message);
		});
	},
};
