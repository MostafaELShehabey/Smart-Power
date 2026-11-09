// Customer list (SP-31): a gold "★ Featured" pill for customers with a won deal.
// ERPNext's own settings load first; this keeps them and its "On Hold" pill wins.
(() => {
	const settings = (frappe.listview_settings["Customer"] = frappe.listview_settings["Customer"] || {});
	settings.add_fields = [...(settings.add_fields || []), "sp_featured"];
	const erpnext_indicator = settings.get_indicator;
	settings.get_indicator = function (doc) {
		const indicator = erpnext_indicator && erpnext_indicator(doc);
		if (indicator) return indicator;
		if (cint(doc.sp_featured)) return [__("★ Featured"), "yellow", "sp_featured,=,1"];
	};
})();
