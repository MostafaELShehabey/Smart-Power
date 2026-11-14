// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Case (SP-46): the rules are on the server (sp_sales/case.py). After the case opens, an
// owner changes only through "Reassign", which asks for a reason and writes the owner history.
const SP_REASSIGN_ROLES = ["SP Admin", "System Manager"];
const SP_OWNERS = [
	{ fieldname: "follow_up_owner", label: "Follow-up Owner" },
	{ fieldname: "quote_creator", label: "Quote Creator" },
	{ fieldname: "requested_by", label: "Requested By" },
];

frappe.ui.form.on("SP Case", {
	refresh(frm) {
		sp_quote_history(frm);
		if (frm.is_new() || !SP_REASSIGN_ROLES.some((r) => frappe.user.has_role(r))) return;
		frm.add_custom_button(__("Reassign"), () => sp_reassign_dialog(frm));
	},
});

function sp_reassign_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Reassign"),
		fields: [
			{
				fieldname: "owner_field",
				fieldtype: "Select",
				label: __("Owner"),
				reqd: 1,
				default: "follow_up_owner",
				options: SP_OWNERS.map((o) => ({ value: o.fieldname, label: __(o.label) })),
			},
			{ fieldname: "to_user", fieldtype: "Link", label: __("To"), options: "User" },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		primary_action_label: __("Reassign"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_sales.case.reassign",
				args: { case: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.show();
}

// Quote history (SP-61): every version, its status and total, and the PDF of every send.
async function sp_quote_history(frm) {
	const field = frm.get_field("quote_history_html");
	if (!field || frm.is_new()) return;
	const { message: quotes } = await frappe.call("smart_power.sp_quotes.quote_send.quote_history", {
		case: frm.doc.name,
	});
	const esc = frappe.utils.escape_html;
	if (!quotes || !quotes.length) {
		field.$wrapper.html(`<p class="text-muted">${esc(__("No quote yet."))}</p>`);
		return;
	}
	const rows = quotes
		.map((q) => {
			const sends = q.sends.length
				? q.sends
						.map(
							(s) => `<div class="small">${esc(frappe.datetime.str_to_user(s.sent_at))} · ${esc(
								__(s.channel)
							)} · ${esc(s.sent_by_name)} · <a href="${esc(s.file_url)}" target="_blank">${esc(
								__("PDF")
							)}</a></div>`
						)
						.join("")
				: `<div class="small text-muted">${esc(__("Not sent"))}</div>`;
			const approved = q.sp_is_approved ? ` <span class="indicator-pill green">${esc(__("Approved"))}</span>` : "";
			return `<tr>
				<td><a href="/app/quotation/${encodeURIComponent(q.name)}">${esc(q.name)}</a></td>
				<td>${esc(q.sp_option_label || "A")}</td>
				<td>${esc(String(q.sp_version || ""))}</td>
				<td>${esc(__(q.sp_status || ""))}${approved}</td>
				<td class="text-right">${esc(format_currency(q.total, q.currency))}</td>
				<td>${sends}</td>
			</tr>`;
		})
		.join("");
	field.$wrapper.html(`<table class="table table-sm"><thead><tr>
		<th>${esc(__("Quotation"))}</th><th>${esc(__("Option"))}</th><th>${esc(__("Version"))}</th>
		<th>${esc(__("Status"))}</th><th class="text-right">${esc(__("Total"))}</th><th>${esc(__("Sends"))}</th>
	</tr></thead><tbody>${rows}</tbody></table>`);
}
