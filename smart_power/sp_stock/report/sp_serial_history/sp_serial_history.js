// Lookup by serial (SP-179): every movement, nameplate photo, commissioning and warranty of one
// motor or pump.

frappe.query_reports["SP Serial History"] = {
	filters: [{ fieldname: "serial_no", label: __("Serial No"), fieldtype: "Data", reqd: 1 }],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "photo" && data && data.photo) {
			const url = encodeURI(data.photo);
			return `<a href="${url}" target="_blank" rel="noopener">${__("Open")}</a>`;
		}
		return default_formatter(value, row, column, data);
	},
};
