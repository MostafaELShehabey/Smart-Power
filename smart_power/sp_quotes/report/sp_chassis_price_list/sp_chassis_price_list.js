// The showroom's chassis price list (SP-166)
frappe.query_reports["SP Chassis Price List"] = {
	filters: [
		{
			fieldname: "factory",
			label: __("Factory"),
			fieldtype: "Link",
			options: "SP Chassis Factory",
			reqd: 1,
		},
	],
};
