// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Africa System consignment (SP-91): a container counted by quantity, never in company stock.
// Reserve for a customer or a station, hand over to the supplier's customer (delivery note),
// return to the supplier; withdrawing into company stock is Withdraw by PO (SP-92). The rules are on
// the server (smart_power.sp_stock.consignment).
const SP_CN_API = "smart_power.sp_stock.consignment";
const SP_CN_COLOURS = { Open: "green", Low: "orange", Empty: "gray" };

frappe.ui.form.on("SP Consignment Container", {
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), SP_CN_COLOURS[frm.doc.status] || "gray");
		if (frm.is_new()) return;
		frm.dashboard.clear_headline();
		frm.dashboard.add_indicator(`${__("Balance")}: ${frm.doc.balance_qty}`, "blue");
		frm.dashboard.add_indicator(`${__("Reserved")}: ${frm.doc.reserved_qty}`, "orange");
		frm.dashboard.add_indicator(`${__("Available")}: ${frm.doc.available_qty}`, "green");
		if (frm.doc.balance_qty > 0) {
			frm.add_custom_button(__("Reserve"), () => sp_cn_move(frm, "Reserve"), __("Move"));
			frm.add_custom_button(__("Hand Over"), () => sp_cn_move(frm, "Hand over"), __("Move"));
			frm.add_custom_button(__("Return to Supplier"), () => sp_cn_move(frm, "Return to supplier"), __("Move"));
		}
		if (frm.doc.balance_qty > 0 && ["SP Admin", "System Manager", "SP Purchase Officer"].some((r) => frappe.user.has_role(r))) {
			// buy panels into company stock at the day's watt price (SP-92)
			frm.add_custom_button(__("Withdraw by PO"), () => sp_cn_withdraw(frm)).addClass("btn-primary");
		}
		if (["SP Admin", "System Manager", "SP Accountant"].some((r) => frappe.user.has_role(r))) {
			frm.add_custom_button(__("Storage Fee"), () => sp_cn_fee(frm));
		}
	},
});

async function sp_cn_move(frm, movement_type) {
	const reservations =
		movement_type === "Hand over"
			? (await frappe.call(`${SP_CN_API}.open_reservations`, { container: frm.doc.name })).message || []
			: [];
	const fields = [
		{ fieldname: "qty", fieldtype: "Int", label: __("Quantity"), reqd: 1 },
		{ fieldname: "movement_date", fieldtype: "Date", label: __("Date"), default: "Today", reqd: 1 },
	];
	if (reservations.length) {
		fields.push({
			fieldname: "reservation",
			fieldtype: "Select",
			label: __("Reservation"),
			options: [
				{ value: "", label: __("None") },
				...reservations.map((r) => ({
					value: r.name,
					label: `${r.customer_name || r.station} · ${r.qty - r.cleared_qty}`,
				})),
			],
			change() {
				const r = reservations.find((x) => x.name === d.get_value("reservation"));
				if (r) {
					d.set_value("qty", r.qty - r.cleared_qty);
					d.set_value("customer_name", r.customer_name || "");
				}
			},
		});
	}
	if (movement_type !== "Return to supplier") {
		fields.push(
			{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer Name") },
			{ fieldname: "customer_phone", fieldtype: "Data", label: __("Customer Phone") }
		);
	}
	if (movement_type === "Reserve") {
		fields.push({ fieldname: "station", fieldtype: "Link", options: "SP Station", label: __("Station") });
	}
	fields.push({ fieldname: "note", fieldtype: "Small Text", label: __("Note") });
	const d = new frappe.ui.Dialog({
		title: `${__(movement_type)} · ${__("Available")}: ${frm.doc.available_qty}`,
		fields,
		primary_action_label: __(movement_type),
		async primary_action(values) {
			const { message } = await frappe.call({
				method: `${SP_CN_API}.make_movement`,
				args: { container: frm.doc.name, movement_type, ...values },
				freeze: true,
			});
			d.hide();
			frm.reload_doc();
			if (movement_type === "Hand over") {
				// the delivery note for the supplier's customer, in Arabic with the letterhead
				const params = new URLSearchParams({
					doctype: "SP Consignment Movement",
					name: message,
					format: "SP Consignment Delivery Note",
					_lang: "ar",
				});
				window.open(frappe.urllib.get_full_url(`/printview?${params}`), "_blank");
			}
		},
	});
	d.show();
}

async function sp_cn_withdraw(frm) {
	const { message: opts } = await frappe.call(`${SP_CN_API}.withdraw_options`, { container: frm.doc.name });
	const reservations = (await frappe.call(`${SP_CN_API}.open_reservations`, { container: frm.doc.name })).message || [];
	const total = () => {
		const v = d.get_values(true);
		return (v.qty || 0) * (v.watt_price || 0) * (v.panel_watts || 0);
	};
	const show_total = () => d.set_df_property("total", "options", `<b>${__("Total")}: ${format_currency(total())}</b>`);
	const d = new frappe.ui.Dialog({
		title: `${__("Withdraw by PO")} · ${__("Available")}: ${frm.doc.available_qty}`,
		fields: [
			{ fieldname: "qty", fieldtype: "Int", label: __("Quantity"), reqd: 1, change: () => show_total() },
			{ fieldname: "watt_price", fieldtype: "Float", label: __("Watt Price (per W)"), reqd: 1, precision: 4, change: () => show_total() }, // sp-allow-number: price decimals
			{ fieldname: "price_date", fieldtype: "Date", label: __("Watt Price Date"), default: "Today", reqd: 1 },
			{ fieldname: "panel_watts", fieldtype: "Float", label: __("Panel Watts"), default: opts.panel_watts, reqd: 1, change: () => show_total() },
			{ fieldname: "total", fieldtype: "HTML" },
			{ fieldname: "col", fieldtype: "Column Break" },
			{
				fieldname: "station",
				fieldtype: "Link",
				options: "SP Station",
				label: __("For Station"),
				description: __("Goes to the station's site warehouse, on its project."),
				get_query: () => ({ filters: { company: opts.company, status: ["!=", "Cancelled"] } }),
			},
			{
				fieldname: "warehouse",
				fieldtype: "Select",
				label: __("Or Into"),
				options: ["", ...opts.warehouses],
				depends_on: "eval:!doc.station",
			},
			...(reservations.length
				? [
						{
							fieldname: "reservation",
							fieldtype: "Select",
							label: __("Reservation"),
							options: [
								{ value: "", label: __("None") },
								...reservations.map((r) => ({ value: r.name, label: `${r.customer_name || r.station} · ${r.qty - r.cleared_qty}` })),
							],
						},
				  ]
				: []),
		],
		primary_action_label: __("Withdraw"),
		async primary_action(values) {
			if (!values.station && !values.warehouse) {
				frappe.msgprint(__("Choose a station or a warehouse."));
				return;
			}
			const { message } = await frappe.call({
				method: `${SP_CN_API}.withdraw`,
				args: { container: frm.doc.name, ...values },
				freeze: true,
			});
			d.hide();
			frm.reload_doc();
			frappe.msgprint({
				title: __("Withdrawn into company stock"),
				indicator: "green",
				message: [
					["Purchase Order", message.purchase_order],
					["Purchase Receipt", message.purchase_receipt],
					["Purchase Invoice", message.purchase_invoice],
				]
					.map(([dt, name]) => `${__(dt)}: <a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`)
					.join("<br>") + `<br><b>${format_currency(message.amount)}</b>`,
			});
		},
	});
	d.show();
	show_total();
}

function sp_cn_fee(frm) {
	const DEDUCTED = "Deducted from the supplier's balance";
	const d = new frappe.ui.Dialog({
		title: __("Storage Fee"),
		fields: [
			{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1 },
			{ fieldname: "fee_date", fieldtype: "Date", label: __("Date"), default: "Today", reqd: 1 },
			{
				fieldname: "settled_by",
				fieldtype: "Select",
				label: __("Settled By"),
				options: [
					{ value: DEDUCTED, label: __(DEDUCTED) },
					{ value: "Paid into an official account", label: __("Paid into an official account") },
				],
				default: DEDUCTED,
				reqd: 1,
			},
			{
				fieldname: "account",
				fieldtype: "Link",
				options: "Account",
				label: __("Official Account"),
				depends_on: `eval:doc.settled_by!=="${DEDUCTED}"`,
				get_query: () => ({ filters: { sp_account_kind: "Official", is_group: 0, disabled: 0 } }),
			},
			{ fieldname: "note", fieldtype: "Data", label: __("Note") },
		],
		primary_action_label: __("Record"),
		async primary_action(values) {
			await frappe.call({ method: `${SP_CN_API}.record_fee`, args: { container: frm.doc.name, ...values }, freeze: true });
			d.hide();
			frm.reload_doc();
		},
	});
	d.show();
}
