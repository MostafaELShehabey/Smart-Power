// P1 purchase orders (SP-82): the Smart Power status as the indicator. The saved views are seed rows.
(function () {
	const settings = (frappe.listview_settings["Purchase Order"] = frappe.listview_settings["Purchase Order"] || {});
	const COLORS = {
		Draft: "gray",
		Sent: "blue",
		"Partly received": "orange",
		Received: "green",
		Closed: "green",
		Cancelled: "red",
	};
	settings.add_fields = [...new Set([...(settings.add_fields || []), "sp_status"])];
	const erpnext_indicator = settings.get_indicator;
	settings.get_indicator = function (doc) {
		if (doc.sp_status) {
			return [__(doc.sp_status), COLORS[doc.sp_status] || "gray", `sp_status,=,${doc.sp_status}`];
		}
		return erpnext_indicator ? erpnext_indicator(doc) : undefined;
	};
})();
