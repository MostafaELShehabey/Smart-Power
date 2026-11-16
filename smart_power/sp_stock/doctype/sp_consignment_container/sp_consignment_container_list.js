// Africa System consignment (SP-91): the status in colour; balance, reserved and available beside it.
frappe.listview_settings["SP Consignment Container"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = { Open: "green", Low: "orange", Empty: "gray" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
