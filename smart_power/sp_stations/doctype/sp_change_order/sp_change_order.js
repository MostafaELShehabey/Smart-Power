// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// S3 Change order (SP-78): add lines to a signed contract or return them (a negative quantity),
// with the customer's approval file. Submitting it updates the contract, the agreed amount and the
// schedule. The rules are on the server (smart_power.sp_stations.change_order).
const SP_CO_API = "smart_power.sp_stations.change_order";

frappe.ui.form.on("SP Change Order", {
	setup(frm) {
		// a signed contract that is still open
		frm.set_query("station", () => ({
			filters: {
				sales_order: ["is", "set"],
				status: ["in", ["Open", "Purchasing", "Installing"]],
			},
		}));
	},

	refresh(frm) {
		sp_co_summary(frm);
		if (frm.doc.docstatus === 0 && frm.doc.station) {
			frm.add_custom_button(__("Return from Contract"), () => sp_co_return_dialog(frm));
		}
	},

	station(frm) {
		sp_co_summary(frm);
	},
});

frappe.ui.form.on("SP Change Order Item", {
	async item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !frm.doc.station || row.so_detail) return;
		const price = await frappe.xcall(`${SP_CO_API}.line_price`, {
			station: frm.doc.station,
			item_code: row.item_code,
		});
		if (!row.qty) await frappe.model.set_value(cdt, cdn, "qty", 1);
		await frappe.model.set_value(cdt, cdn, "rate", price.rate);
		if (price.cost !== null && price.cost !== undefined) {
			await frappe.model.set_value(cdt, cdn, "cost", price.cost);
		}
	},
	qty(frm, cdt, cdn) {
		sp_co_amount(frm, cdt, cdn);
	},
	rate(frm, cdt, cdn) {
		sp_co_amount(frm, cdt, cdn);
	},
	items_remove(frm) {
		sp_co_total(frm);
	},
});

function sp_co_amount(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	sp_co_total(frm);
}

function sp_co_total(frm) {
	const delta = (frm.doc.items || []).reduce((sum, r) => sum + flt(r.qty) * flt(r.rate), 0);
	frm.set_value("delta_amount", delta);
	sp_co_summary(frm);
}

// what the contract becomes: agreed before → after (an intro, so a new form shows it too)
function sp_co_summary(frm) {
	frm.set_intro("");
	if (!frm.doc.station || !frm.doc.agreed_before) return;
	const before = flt(frm.doc.agreed_before);
	const delta = flt(frm.doc.delta_amount);
	const after = frm.doc.docstatus === 1 ? flt(frm.doc.agreed_after) : before + delta;
	const change = `${delta >= 0 ? "+" : ""}${format_currency(delta)}`;
	frm.set_intro(
		`${__("Agreed: {0} → {1}", [format_currency(before), format_currency(after)])} (${change})`,
		delta < 0 ? "orange" : "blue"
	);
}

// a return comes off a contract line, at the contract's price
async function sp_co_return_dialog(frm) {
	const lines = await frappe.xcall(`${SP_CO_API}.contract_lines`, { station: frm.doc.station });
	if (!lines.length) {
		frappe.msgprint(__("Nothing on the contract can be returned: everything is delivered."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Return from Contract"),
		size: "large",
		fields: [
			{
				fieldname: "lines",
				fieldtype: "Table",
				label: __("Contract Lines"),
				cannot_add_rows: true,
				in_place_edit: true,
				data: lines.map((l) => ({ ...l, return_qty: 0 })),
				fields: [
					{ fieldname: "item_code", fieldtype: "Data", label: __("Item Code"), in_list_view: 1, read_only: 1, columns: 2 }, // sp-allow-number: grid column width
					{ fieldname: "item_name", fieldtype: "Data", label: __("Item Name"), in_list_view: 1, read_only: 1, columns: 3 }, // sp-allow-number: grid column width
					{ fieldname: "left", fieldtype: "Float", label: __("Not Delivered"), in_list_view: 1, read_only: 1, columns: 2 }, // sp-allow-number: grid column width
					{ fieldname: "rate", fieldtype: "Currency", label: __("Contract Price"), in_list_view: 1, read_only: 1, columns: 2 }, // sp-allow-number: grid column width
					{ fieldname: "return_qty", fieldtype: "Float", label: __("Return Qty"), in_list_view: 1, columns: 1 },
					{ fieldname: "so_detail", fieldtype: "Data", hidden: 1 },
					{ fieldname: "cost", fieldtype: "Currency", hidden: 1 },
				],
			},
		],
		primary_action_label: __("Add Returns"),
		primary_action: ({ lines: picked }) => {
			const chosen = (picked || []).filter((l) => flt(l.return_qty) > 0);
			for (const l of chosen) {
				if (flt(l.return_qty) > flt(l.left)) {
					frappe.throw(__("Only {0} of {1} can be returned.", [l.left, l.item_code]));
				}
			}
			// the empty row a new form starts with is replaced, not kept above the returns
			frm.doc.items = (frm.doc.items || []).filter((r) => r.item_code);
			for (const l of chosen) {
				const row = frm.add_child("items", {
					item_code: l.item_code,
					item_name: l.item_name,
					qty: -flt(l.return_qty),
					rate: l.rate,
					amount: -flt(l.return_qty) * flt(l.rate),
					so_detail: l.so_detail,
				});
				if (l.cost !== null && l.cost !== undefined) row.cost = l.cost;
			}
			frm.refresh_field("items");
			sp_co_total(frm);
			dialog.hide();
		},
	});
	dialog.show();
}
