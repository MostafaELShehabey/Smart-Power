// AR1 Customer balances (SP-120): per customer and station; the statement prints from each row.
frappe.query_reports["SP Customer Balances"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{
			fieldname: "collection_owner",
			label: __("Collection Owner"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Open",
				"Purchasing",
				"Installing",
				"Technically closed",
				"Financially closed",
			].map((value) => ({ value, label: value ? __(value) : "" })),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "statement") {
			if (!data || !data.station) return "";
			const url = frappe.urllib.get_full_url(
				"/printview?" +
					new URLSearchParams({
						doctype: "SP Station",
						name: data.station,
						format: "SP Customer Statement",
						_lang: "ar",
					}).toString(),
			);
			return `<a href="${url}" target="_blank">${__("Print")}</a>`;
		}
		if (column.fieldname === "station") {
			// the station's number, not its title (the customer's name)
			if (!data || !data.station) return "";
			const station = frappe.utils.escape_html(data.station);
			return `<a href="/app/sp-station/${encodeURIComponent(data.station)}">${station}</a>`;
		}
		const out = default_formatter(value, row, column, data);
		if (column.fieldname === "overdue" && data && data.overdue > 0) {
			return `<span style="color: var(--red-600); font-weight: 600">${out}</span>`;
		}
		return out;
	},
};
