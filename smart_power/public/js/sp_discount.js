// F4 Give a discount (SP-68): on the quote total or one section, or the customer's last-minute
// ask (العشم). Sale prices only. No approval gate: above the giver's limit the discount is kept
// and the admin is told. A sent version gets a new version. The rules are on the server
// (smart_power.sp_quotes.discounts). Used by the case form (F2) and the quote form.
frappe.provide("smart_power");

smart_power.discount_dialog = async function (quotation, on_done) {
	const API = "smart_power.sp_quotes.discounts";
	const { message: opts } = await frappe.call(`${API}.discount_options`, { quotation });
	const esc = frappe.utils.escape_html;
	const money = (v) => format_currency(v, opts.currency);
	const scopes = [{ value: "", label: `${__("Quote total")} (${money(opts.total)})` }].concat(
		opts.sections.map((s) => ({ value: s.section, label: `${s.section} (${money(s.total)})` }))
	);
	const given = opts.discounts.length
		? `<div class="small mb-2"><b>${esc(__("Discounts already given"))}</b>${opts.discounts
				.map(
					(d) => `<div>${esc(__(d.kind))} · ${esc(d.applies_to || __("Quote total"))} · ${esc(
						money(d.amount)
					)}${d.note ? ` · ${esc(d.note)}` : ""}</div>`
				)
				.join("")}</div>`
		: "";
	const notes = [
		opts.is_sent ? __("This version was sent: the discount makes a new version.") : "",
		opts.limit_pct
			? __("Your limit is {0}% of the total; above it the discount is kept and the admin is told.", [
					opts.limit_pct,
			  ])
			: "",
	]
		.filter(Boolean)
		.map((n) => `<div class="small text-muted">${esc(n)}</div>`)
		.join("");
	const dialog = new frappe.ui.Dialog({
		title: __("Give a discount"),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `${given}<div class="mb-2">${esc(__("Total"))}: <b>${esc(
					money(opts.grand_total)
				)}</b></div>${notes}`,
			},
			{
				fieldname: "kind",
				fieldtype: "Select",
				label: __("Kind"),
				reqd: 1,
				default: "Discount",
				options: [
					{ value: "Discount", label: __("Discount") },
					{ value: "Last-minute ask", label: __("Last-minute ask") },
				],
			},
			{ fieldname: "applies_to", fieldtype: "Select", label: __("Applies To"), options: scopes },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "percent", fieldtype: "Percent", label: __("Percent") },
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				options: opts.currency,
				depends_on: "eval:!doc.percent",
			},
			{ fieldname: "sec", fieldtype: "Section Break" },
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
		],
		primary_action_label: __("Give discount"),
		primary_action: async (values) => {
			const { message: result } = await frappe.call({
				method: `${API}.give_discount`,
				args: { quotation, ...values },
				freeze: true,
			});
			dialog.hide();
			const lines = [
				__("Discount {0} given. New total: {1}.", [money(result.amount), money(result.total)]),
			];
			if (result.new_version) lines.push(__("New version {0}: send it to the customer.", [result.quotation]));
			result.warnings.forEach((w) => lines.push(w));
			frappe.msgprint({
				title: __("Discount given"),
				message: lines.map((l) => `<p>${esc(l)}</p>`).join(""),
				indicator: result.warnings.length ? "orange" : "green",
			});
			on_done && on_done(result);
		},
	});
	dialog.show();
};
