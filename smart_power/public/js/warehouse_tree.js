// The stores tree (BUG-34). Smart Power is one company, so the tree opens on it and has no company
// filter. ERPNext takes the first company by name when the desk has no default company.
(() => {
	const settings = frappe.treeview_settings["Warehouse"];
	const company = ((settings && settings.filters) || []).find((f) => f.fieldname === "company");
	const own = frappe.defaults.get_user_default("Company") || frappe.boot.sp_company;
	if (!company || !own || !(company.options || []).includes(own)) return;
	company.default = own;
	company.hidden = 1;
})();
