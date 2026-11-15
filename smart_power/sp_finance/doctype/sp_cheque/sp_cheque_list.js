// A5 Cheque register (SP-118): statuses in colour; a cheque due within a week stands out.
frappe.listview_settings["SP Cheque"] = {
	add_fields: ["status", "due_date"],
	get_indicator(doc) {
		const colours = {
			Received: "blue",
			Due: "orange",
			Deposited: "purple",
			Collected: "green",
			Bounced: "red",
			"With lawyer": "red",
		};
		const soon = frappe.datetime.get_day_diff(doc.due_date, frappe.datetime.get_today()) <= 7; // sp-allow-number: a week
		const open = ["Received", "Due", "Deposited"].includes(doc.status);
		return [__(doc.status), open && soon ? "red" : colours[doc.status], `status,=,${doc.status}`];
	},
};
