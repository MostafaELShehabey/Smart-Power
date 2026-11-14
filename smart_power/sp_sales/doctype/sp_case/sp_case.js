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
		sp_followup_view(frm);
		if (sp_can_log_call(frm)) {
			frm.add_custom_button(__("Log call"), () => sp_log_call_dialog(frm));
		}
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

// Follow-up (SP-67, F2 / F3): the call timeline and the quote at sale prices only, a "Log call"
// dialog, and after a "Lost" call the lost dialog with its reason.
const SP_CLOSED = ["Won", "Lost"];

function sp_can_log_call(frm) {
	return !frm.is_new() && !SP_CLOSED.includes(frm.doc.status) && frappe.model.can_create("SP Call Log");
}

function sp_log_call_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Log call"),
		fields: [
			{
				fieldname: "result",
				fieldtype: "Link",
				label: __("Result"),
				options: "SP List Value",
				reqd: 1,
				get_query: () => ({ filters: { list_name: "Call Result", is_active: 1 } }),
			},
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			{
				fieldname: "next_call_at",
				fieldtype: "Datetime",
				label: __("Next Call"),
				description: __("Becomes a call task for the follow-up owner."),
			},
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			const { message } = await frappe.call({
				method: "smart_power.sp_sales.followup.log_call",
				args: { case: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			if (message && message.lost) {
				sp_lost_dialog(frm, values.note);
			} else {
				frm.reload_doc();
			}
		},
	});
	dialog.show();
}

function sp_lost_dialog(frm, note) {
	const dialog = new frappe.ui.Dialog({
		title: __("Mark Lost"),
		fields: [
			{
				fieldname: "lost_reason",
				fieldtype: "Link",
				label: __("Lost Reason"),
				options: "SP List Value",
				reqd: 1,
				get_query: () => ({ filters: { list_name: "Lost Reason", is_active: 1 } }),
			},
			{ fieldname: "lost_note", fieldtype: "Small Text", label: __("Lost Note"), default: note },
		],
		primary_action_label: __("Mark Lost"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_sales.followup.mark_lost",
				args: { case: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.on_hide = () => frm.reload_doc();
	dialog.show();
}

async function sp_followup_view(frm) {
	const field = frm.get_field("followup_html");
	if (!field || frm.is_new()) return;
	const { message: view } = await frappe.call("smart_power.sp_sales.followup.case_view", {
		case: frm.doc.name,
	});
	const esc = frappe.utils.escape_html;
	const calls = view.calls.length
		? view.calls
				.map(
					(c) => `<div class="sp-call border-bottom py-2">
				<div><b>${esc(c.result_label)}</b> · ${esc(frappe.datetime.str_to_user(c.call_time))} · ${esc(
						c.logged_by_name || ""
					)}</div>
				${c.note ? `<div>${esc(c.note)}</div>` : ""}
				${
					c.next_call_at
						? `<div class="small text-muted">${esc(__("Next Call"))}: ${esc(
								frappe.datetime.str_to_user(c.next_call_at)
						  )}</div>`
						: ""
				}
			</div>`
				)
				.join("")
		: `<p class="text-muted">${esc(__("No call yet."))}</p>`;
	let quote = `<p class="text-muted">${esc(__("No sent quote yet."))}</p>`;
	const q = view.quote;
	if (q) {
		const money = (v) => esc(format_currency(v, q.currency));
		const lines = q.lines
			.map(
				(l) => `<tr><td>${esc(String(l.no))}</td><td>${esc(l.description)}</td>
				<td class="text-right">${esc(String(l.qty))} ${esc(l.uom || "")}</td>
				<td class="text-right">${money(l.rate)}</td><td class="text-right">${money(l.amount)}</td></tr>`
			)
			.join("");
		const schedule = q.schedule.length
			? `<div class="small mt-2"><b>${esc(__("Payment Schedule"))}</b>${q.schedule
					.map(
						(r) => `<div>${esc(frappe.datetime.str_to_user(r.due_date))} · ${money(r.amount)} ${esc(
							r.description || ""
						)}</div>`
					)
					.join("")}</div>`
			: "";
		quote = `<div class="mb-1"><a href="/app/quotation/${encodeURIComponent(q.name)}">${esc(q.name)}</a>
			· ${esc(__("Option"))} ${esc(q.option || "A")} · ${esc(__("Version"))} ${esc(String(q.version || ""))}
			· ${esc(__(q.status || ""))}${
			q.valid_till ? ` · ${esc(__("Valid Till"))} ${esc(frappe.datetime.str_to_user(q.valid_till))}` : ""
		}</div>
			<table class="table table-sm"><thead><tr><th>#</th><th>${esc(__("Description"))}</th>
			<th class="text-right">${esc(__("Qty"))}</th><th class="text-right">${esc(__("Rate"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th></tr></thead><tbody>${lines}</tbody>
			<tfoot><tr><th colspan="4">${esc(__("Total"))}</th><th class="text-right">${money(q.total)}</th></tr></tfoot>
			</table>${schedule}`;
	}
	field.$wrapper.html(`<div class="row">
		<div class="col-md-5"><h6>${esc(__("Calls"))}</h6>${calls}</div>
		<div class="col-md-7"><h6>${esc(__("Quote"))}</h6>${quote}</div>
	</div>`);
}
