// I3 Stock by location and owner (SP-87): company stock and the supplier's consignment, never
// mixed. A row's Movements link opens its stock ledger (or the supplier's containers).

frappe.query_reports["SP Stock by Owner"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "location",
			label: __("Stock Location"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({ filters: { is_group: 0 } }),
		},
		{
			fieldname: "owner",
			label: __("Stock Owner"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("All") },
				{ value: "company", label: __("Smart Power") },
				{ value: "supplier", label: __("Supplier on consignment") },
			],
		},
		{ fieldname: "show_zero", label: __("Show empty rows"), fieldtype: "Check" },
		{ fieldname: "below_reorder", label: __("At or under the reorder level"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname !== "history" || !data || !data.item_code) {
			return default_formatter(value, row, column, data);
		}
		let route;
		if (data.owner_kind === "supplier") {
			route = `/app/sp-consignment-container?item=${encodeURIComponent(data.item_code)}`;
		} else {
			const params = new URLSearchParams({ item_code: data.item_code, warehouse: data.location });
			route = `/app/query-report/Stock Ledger?${params}`;
		}
		return `<a href="${route}">${frappe.utils.escape_html(__("Show Movements"))}</a>`;
	},
};
