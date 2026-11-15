// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A5 Cheque register (SP-118): one cheque, its holder, and the next step:
// Deposited (taken to the Post) -> Collected (its payment posts) or Bounced -> With lawyer.
// The rules are on the server (smart_power.sp_finance.cheques).
const SP_CHQ_API = "smart_power.sp_finance.cheques";
const SP_CHQ_COLOURS = {
	Received: "blue",
	Due: "orange",
	Deposited: "purple",
	Collected: "green",
	Bounced: "red",
	"With lawyer": "red",
};

frappe.ui.form.on("SP Cheque", {
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), SP_CHQ_COLOURS[frm.doc.status] || "gray");
		if (frm.is_new()) return;
		const act = (label, method, confirm, extra) =>
			frm.add_custom_button(label, () =>
				frappe.confirm(confirm, async () => {
					await frappe.call({ method: `${SP_CHQ_API}.${method}`, args: { name: frm.doc.name, ...(extra || {}) }, freeze: true });
					frm.reload_doc();
				})
			);
		const s = frm.doc.status;
		if (["Received", "Due"].includes(s)) {
			act(__("Deposited"), "mark_deposited", __("Mark cheque {0} as taken to the Post?", [frm.doc.cheque_no]));
		}
		if (["Received", "Due", "Deposited"].includes(s)) {
			act(
				__("Collected"),
				"mark_collected",
				__("Cheque {0} collected? Its payment of {1} posts to the Post.", [frm.doc.cheque_no, format_currency(frm.doc.amount)])
			).addClass("btn-primary");
		}
		if (["Received", "Due", "Deposited", "Collected"].includes(s)) {
			frm.add_custom_button(__("Bounced"), () =>
				frappe.prompt(
					{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
					async ({ note }) => {
						await frappe.call({ method: `${SP_CHQ_API}.mark_bounced`, args: { name: frm.doc.name, note }, freeze: true });
						frm.reload_doc();
					},
					__("Cheque bounced"),
					__("Bounced")
				)
			);
		}
		if (s === "Bounced") {
			act(__("With lawyer"), "mark_with_lawyer", __("Hand cheque {0} to the lawyer?", [frm.doc.cheque_no]));
		}
	},
});
