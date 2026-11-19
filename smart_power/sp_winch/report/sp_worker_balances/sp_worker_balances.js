// Worker balances (SP-181): what each crew member still owes on his advances.
frappe.query_reports["SP Worker Balances"] = {
	filters: [
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Vehicle" },
		{ fieldname: "include_repaid", label: __("Include repaid advances"), fieldtype: "Check" },
	],
};
