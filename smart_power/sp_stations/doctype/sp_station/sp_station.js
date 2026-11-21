// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Station (SP-73): the owner chips (sales, execution, collection) and the money chips
// (Agreed · Paid, confirmed only · Remaining · Next due) at the top of the station. The admin
// records a write-off so a station with money left can close financially. The rules are on the
// server (smart_power.sp_stations).
//
// S2 Station record (SP-76): 11 tabs, each filled from its own API the first time it is opened
// (smart_power.sp_stations.station_tabs). A tab the user's roles do not see is hidden here and
// refused by the server; amounts come only to those who see the station's money.
const SP_ST_ADMIN_ROLES = ["SP Admin", "System Manager"];
const SP_ST_TABS_API = "smart_power.sp_stations.station_tabs";
const SP_ST_TABS = [
	"overview",
	"scope",
	"agreement",
	"payments",
	"purchasing",
	"site",
	"programming",
	"documents",
	"warranty",
	"costs",
	"history",
];
// the next step of the station, by status (the "SP Station" workflow's actions)
const SP_ST_NEXT = {
	Open: "Start Purchasing",
	Purchasing: "Start Installing",
	Installing: "Close Technically",
	"Technically closed": "Close Financially",
};
const SP_ST_TRANSFER_ROLES = ["SP Purchase Officer", "SP Project Manager", ...SP_ST_ADMIN_ROLES];

frappe.ui.form.on("SP Station", {
	refresh(frm) {
		if (frm.is_new()) return;
		// read-only for sales after the contract (SP-35); the banner leads the owners line
		if (frm.doc.__onload?.sp_read_only) frm.disable_form();
		sp_station_tabs(frm);
		sp_station_next_step(frm);
		sp_station_chips(frm);
		// photos of the finished station, tagged usable for marketing (SP-53)
		smart_power.site_photos(frm, "photos_html", "");
		const admin = SP_ST_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
		if (frm.doc.status !== "Cancelled" && frm.get_perm(1, "read")) {
			frm.add_custom_button(__("Record Payment"), () =>
				smart_power.record_payment_dialog({ station: frm.doc.name }, () => frm.reload_doc())
			);
		}
		// financed by the Agri Bank: the customer's own share is advanced and tracked apart (SP-121)
		const bank_financing = admin || frappe.user.has_role("SP Bank Financing");
		if (bank_financing && frm.doc.financing_type === "Financing Type-AGRI" && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Agri Bank Advance"), () =>
				frappe.new_doc("SP Customer Advance", { station: frm.doc.name })
			);
		}
		if (admin && frm.doc.remaining_amount > 0 && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Record Write-off"), () => sp_station_write_off(frm));
		}
		// cancel after the deposit: refunds, reservations, orders and the site's goods (SP-176)
		if (admin && ["Open", "Purchasing", "Installing"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Cancel Station"), () => sp_station_cancel(frm), __("Actions"));
		}
		// the referrer's commission, as a payable to the referrer (SP-177)
		if (admin && flt(frm.doc.commission_amount) > 0 && frm.doc.status !== "Cancelled") {
			sp_station_commission_button(frm);
		}
		// S4 hand the execution or the collection to someone else from a date (SP-79)
		if (admin && !["Financially closed", "Cancelled"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Reassign"), () => sp_station_reassign(frm));
		}
		if (frm.doc.sales_order) {
			frm.add_custom_button(__("Contract"), () => frappe.set_route("Form", "Sales Order", frm.doc.sales_order), __("View"));
		} else if (frm.doc.case) {
			sp_station_contract_button(frm);
		}
		if (frm.doc.project) {
			frm.add_custom_button(__("Project"), () => frappe.set_route("Form", "Project", frm.doc.project), __("View"));
		}
		// S3 a change to the signed contract (SP-78)
		if (
			frm.doc.sales_order &&
			["Open", "Purchasing", "Installing"].includes(frm.doc.status) &&
			frappe.model.can_create("SP Change Order")
		) {
			frm.add_custom_button(
				__("Change Order"),
				() => frappe.new_doc("SP Change Order", { station: frm.doc.name }),
				__("Create")
			);
		}
		// PR1 programming and the operation date, one per system (SP-97)
		if (frm.doc.status !== "Cancelled" && frappe.model.can_create("SP Commissioning")) {
			frm.add_custom_button(
				__("Commissioning"),
				() => frappe.new_doc("SP Commissioning", { station: frm.doc.name }),
				__("Create")
			);
		}
	},
});

function sp_station_chips(frm) {
	const money = (v) => format_currency(v || 0, frm.doc.currency);
	frm.dashboard.clear_headline();
	// the money chips only for those who see the station's money (SP-76: not the site view)
	const amounts = frm.get_perm(1, "read");
	const due = frm.doc.next_due_date
		? `${money(frm.doc.next_due_amount)} · ${frappe.datetime.str_to_user(frm.doc.next_due_date)}`
		: __("None");
	if (amounts) sp_station_money_chips(frm, money, due);
	sp_station_owner_line(frm);
}

function sp_station_money_chips(frm, money, due) {
	frm.dashboard.add_indicator(`${__("Agreed")}: ${money(frm.doc.agreed_amount)}`, "blue");
	frm.dashboard.add_indicator(`${__("Paid")}: ${money(frm.doc.paid_amount)}`, "green");
	if (frm.doc.pending_amount > 0) {
		frm.dashboard.add_indicator(`${__("Pending")}: ${money(frm.doc.pending_amount)}`, "yellow");
	}
	frm.dashboard.add_indicator(
		`${__("Remaining")}: ${money(frm.doc.remaining_amount)}`,
		frm.doc.remaining_amount > 0 ? "orange" : "green"
	);
	const overdue = frm.doc.next_due_date && frm.doc.next_due_date < frappe.datetime.get_today();
	frm.dashboard.add_indicator(`${__("Next Due")}: ${due}`, overdue ? "red" : "gray");
}

function sp_station_owner_line(frm) {
	const names = frm.doc.__onload?.sp_owner_names || {};
	const owner = (label, user) => (user ? `${__(label)}: ${names[user] || frappe.user.full_name(user)}` : "");
	const owners = [
		owner("Sales", frm.doc.sales_owner),
		owner("Execution", frm.doc.execution_owner),
		owner("Collection", frm.doc.collection_owner),
	].filter(Boolean);
	const parts = owners.map((o) => frappe.utils.escape_html(o));
	// a hand-over from a later date (SP-79)
	for (const r of frm.doc.__onload?.sp_scheduled_reassign || []) {
		parts.push(frappe.utils.escape_html(__("{0} moves to {1} on {2}", [r.owner, r.to_user, r.from_date]))); // sp-allow-number: placeholder index
	}
	const read_only = frm.doc.__onload?.sp_read_only;
	if (read_only) parts.unshift(`<b>${frappe.utils.escape_html(read_only)}</b>`);
	if (parts.length) frm.dashboard.set_headline(parts.join(" · "), read_only ? "orange" : undefined);
}

function sp_station_write_off(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Record Write-off"),
		fields: [
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				reqd: 1,
				default: frm.doc.remaining_amount,
				description: __("Remaining: {0}", [format_currency(frm.doc.remaining_amount)]),
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		primary_action_label: __("Record Write-off"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_stations.station.record_write_off",
				args: { station: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.show();
}

// Cancel the station (SP-176): every confirmed payment is refunded (pending confirmation), the
// reservations go, draft orders are deleted and submitted ones flagged, the site's goods go back.
async function sp_station_cancel(frm) {
	const api = "smart_power.sp_stations.cancel";
	const p = await frappe.xcall(`${api}.cancel_preview`, { station: frm.doc.name });
	const esc = frappe.utils.escape_html;
	const refunds = p.refunds
		.map((r) => `<li>${esc(frappe.datetime.str_to_user(r.date))} · ${format_currency(r.amount)} · ${esc(r.account)}</li>`)
		.join("");
	const total = p.refunds.reduce((sum, r) => sum + flt(r.amount), 0);
	const orders = [
		p.draft_orders.length ? __("Draft purchase orders deleted: {0}", [p.draft_orders.join(", ")]) : "",
		p.submitted_orders.length
			? __("Submitted purchase orders flagged to the projects manager: {0}", [p.submitted_orders.join(", ")])
			: "",
	].filter(Boolean);
	const fields = [
		{
			fieldtype: "HTML",
			fieldname: "summary",
			options:
				`<p>${esc(__("Refund, pending the admin's confirmation: {0}", [format_currency(total)]))}</p>` +
				(refunds ? `<ul>${refunds}</ul>` : `<p class="text-muted">${esc(__("No confirmed payment to refund."))}</p>`) +
				orders.map((o) => `<p>${esc(o)}</p>`).join(""),
		},
		{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1 },
	];
	const transit = p.refunds.filter((r) => !r.official);
	if (transit.length) fields.push({ fieldtype: "Section Break", label: __("Refund From") });
	transit.forEach((r, i) =>
		fields.push({
			fieldtype: "Select",
			fieldname: `account_${i}`,
			label: __("{0} received in {1}", [format_currency(r.amount), r.account]),
			options: ["", ...p.accounts],
			reqd: 1,
		})
	);
	if (p.lines.length) fields.push({ fieldtype: "Section Break", label: __("At the Site") });
	p.lines.forEach((l, i) =>
		fields.push({
			fieldtype: "Select",
			fieldname: `fate_${i}`,
			label: `${l.item_name} · ${l.qty}`,
			options: [
				{ value: "To stock", label: __("To stock") },
				...(l.purchase_receipt ? [{ value: "Return to supplier", label: __("Return to supplier") }] : []),
			],
			default: "To stock",
		})
	);
	const dialog = new frappe.ui.Dialog({
		title: __("Cancel Station {0}", [frm.doc.name]),
		fields,
		primary_action_label: __("Cancel Station"),
		primary_action: async (values) => {
			const accounts = {};
			transit.forEach((r, i) => (accounts[r.payment] = values[`account_${i}`]));
			const fates = {};
			p.lines.forEach((l, i) => (fates[l.item_code] = values[`fate_${i}`]));
			await frappe.xcall(`${api}.cancel_station`, {
				station: frm.doc.name,
				reason: values.reason,
				accounts,
				fates,
			});
			dialog.hide();
			frappe.show_alert({ message: __("Station cancelled."), indicator: "orange" });
			frm.reload_doc();
		},
	});
	dialog.$wrapper.find(".btn-modal-primary").attr("data-variant", "danger");
	dialog.show();
}

// Post the referrer commission now (SP-177): the Manual setting, or one the event did not post.
async function sp_station_commission_button(frm) {
	const api = "smart_power.sp_stations.commission";
	const state = await frappe.xcall(`${api}.commission_state`, { station: frm.doc.name });
	if (state.posted || !state.can_post) return;
	frm.add_custom_button(
		__("Post Commission"),
		() => {
			if (!frm.doc.sales_partner) {
				frappe.msgprint(__("Set the station's referrer first."));
				return;
			}
			frappe.confirm(
				__("Post the referrer commission of {0} to {1}?", [
					format_currency(frm.doc.commission_amount),
					frm.doc.sales_partner,
				]),
				async () => {
					await frappe.xcall(`${api}.post_commission`, { station: frm.doc.name });
					frappe.show_alert({ message: __("Commission posted."), indicator: "green" });
					frm.reload_doc();
				}
			);
		},
		__("Actions")
	);
}

// S4 Reassign (SP-79): the execution or the collection owner, from a date, with a reason.
async function sp_station_reassign(frm) {
	const api = "smart_power.sp_stations.reassign";
	const users = {};
	const load = async (kind) => {
		users[kind] = users[kind] || (await frappe.xcall(`${api}.eligible_users`, { kind }));
		dialog.fields_dict.to_user.df.options = users[kind];
		dialog.fields_dict.to_user.refresh();
	};
	const dialog = new frappe.ui.Dialog({
		title: __("Reassign"),
		fields: [
			{
				fieldname: "kind",
				fieldtype: "Select",
				label: __("Owner"),
				reqd: 1,
				default: "collection",
				options: [
					{ value: "collection", label: __("Collection Owner") },
					{ value: "execution", label: __("Execution Owner") },
				],
				change: () => load(dialog.get_value("kind")),
			},
			{ fieldname: "to_user", fieldtype: "Select", label: __("To"), reqd: 1, options: [] },
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
				description: __("A later date waits as Scheduled; the change happens on that day."),
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		primary_action_label: __("Reassign"),
		primary_action: async (values) => {
			const result = await frappe.xcall(`${api}.reassign_station`, { station: frm.doc.name, ...values });
			dialog.hide();
			frappe.show_alert({
				message: result.applied
					? __("Reassigned.")
					: __("Scheduled from {0}.", [frappe.datetime.str_to_user(result.from_date)]),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
	dialog.show();
	await load("collection");
}

// The contract (SP-74) when the station was opened before it: made from the case's approved version.
function sp_station_contract_button(frm) {
	frm.add_custom_button(__("Make Contract"), () =>
		frappe.confirm(__("Make the contract (Sales Order) from the case's approved version?"), async () => {
			const { message: result } = await frappe.call({
				method: "smart_power.sp_stations.contract.make_contract",
				args: { case: frm.doc.case },
				freeze: true,
			});
			frappe.set_route("Form", "Sales Order", result.sales_order);
		})
	);
}

// --- S2 tabs (SP-76) ----------------------------------------------------------------------------

async function sp_station_tabs(frm) {
	const { message } = await frappe.call({ method: `${SP_ST_TABS_API}.tabs`, args: { station: frm.doc.name } });
	frm.__sp_tabs = message;
	frm.__sp_drawn = {};
	for (const tab of frm.layout.tabs) {
		const name = (tab.df.fieldname || "").replace(/^tab_/, "");
		if (!SP_ST_TABS.includes(name)) continue;
		tab.df.hidden = message.tabs.includes(name) ? 0 : 1;
		tab.tab_link
			.find("button")
			.off("click.sp_station")
			.on("click.sp_station", () => sp_station_draw(frm, name));
	}
	frm.layout.refresh_tabs();
	const active = frm.get_active_tab?.();
	const first = (active?.df.fieldname || "").replace(/^tab_/, "");
	sp_station_draw(frm, message.tabs.includes(first) ? first : message.tabs[0]);
}

async function sp_station_draw(frm, name) {
	if (!name || frm.__sp_drawn?.[name] || !frm.__sp_tabs?.tabs.includes(name)) return;
	frm.__sp_drawn[name] = true;
	const field = frm.get_field(`${name}_html`);
	if (!field) return;
	field.$wrapper.html(`<p class="text-muted small">${__("Loading...")}</p>`);
	try {
		const { message } = await frappe.call({
			method: `${SP_ST_TABS_API}.tab`,
			args: { station: frm.doc.name, name },
		});
		field.$wrapper.html(SP_ST_RENDER[name](message, frm.__sp_tabs.amounts, frm));
	} catch (e) {
		frm.__sp_drawn[name] = false;
		field.$wrapper.empty();
	}
}

const sp_st_esc = (v) => frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
const SP_ST_COLORS = {
	Paid: "green",
	Confirmed: "green",
	Collected: "green",
	Received: "green",
	Done: "green",
	Reviewed: "green",
	Repaid: "green",
	Active: "green",
	"Partly paid": "orange",
	Pending: "orange",
	Due: "blue",
	Open: "blue",
	Issued: "blue",
	Sent: "blue",
	Overdue: "red",
	Bounced: "red",
	Rejected: "red",
	Discrepancy: "red",
	Flagged: "red",
	Expired: "gray",
	Draft: "gray",
};

function sp_st_cell(col, row) {
	const value = typeof col.value === "function" ? col.value(row) : row[col.key];
	if (value === undefined || value === null || value === "") return "";
	if (col.type === "date") return sp_st_esc(frappe.datetime.str_to_user(value));
	if (col.type === "money") return sp_st_esc(format_currency(value));
	if (col.type === "link") {
		return `<a href="/app/${frappe.router.slug(col.doctype)}/${encodeURIComponent(value)}">${sp_st_esc(value)}</a>`;
	}
	if (col.type === "status") {
		return `<span class="indicator-pill ${SP_ST_COLORS[value] || "gray"}">${sp_st_esc(__(value))}</span>`;
	}
	if (col.type === "file") {
		return `<a href="${encodeURI(value)}" target="_blank" rel="noopener">${sp_st_esc(col.text ? col.text(row) : value)}</a>`;
	}
	return sp_st_esc(value);
}

// a table of rows; money columns only for those who see amounts
function sp_st_table(columns, rows, amounts, empty) {
	if (!rows?.length) return `<p class="text-muted small">${sp_st_esc(empty || __("Nothing yet."))}</p>`;
	const cols = columns.filter((c) => c.type !== "money" || amounts);
	const head = cols.map((c) => `<th>${sp_st_esc(c.label)}</th>`).join("");
	const body = rows.map((r) => `<tr>${cols.map((c) => `<td>${sp_st_cell(c, r)}</td>`).join("")}</tr>`).join("");
	return `<div class="table-responsive"><table class="table table-sm table-bordered"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

const sp_st_h = (title) => `<h6 class="mt-4 mb-2">${sp_st_esc(title)}</h6>`;

function sp_st_facts(pairs) {
	const items = pairs
		.filter(([, value]) => value !== undefined && value !== null && value !== "")
		.map(
			([label, value]) =>
				`<div class="col-sm-4 mb-2"><div class="text-muted small">${sp_st_esc(label)}</div><div>${value}</div></div>`
		)
		.join("");
	return `<div class="row">${items}</div>`;
}

const sp_st_date = (v) => (v ? sp_st_esc(frappe.datetime.str_to_user(v)) : "");
const sp_st_money = (v) => sp_st_esc(format_currency(v || 0));

const SP_ST_RENDER = {
	overview(d, amounts) {
		const alerts = d.alerts.length
			? `<div class="alert alert-warning">${d.alerts.map((a) => `<div>${sp_st_esc(a)}</div>`).join("")}</div>`
			: "";
		const timeline = d.timeline.length
			? `<ul class="list-unstyled">${d.timeline
					.map((e) => `<li><span class="text-muted">${sp_st_date(e.date)}</span> · ${sp_st_esc(e.label)}</li>`)
					.join("")}</ul>`
			: `<p class="text-muted small">${__("Nothing yet.")}</p>`;
		return (
			alerts +
			sp_st_facts([
				[__("Contract Date"), sp_st_date(d.dates.contract_date)],
				[__("Next Delivery"), sp_st_date(d.dates.next_delivery)],
				[__("Operation Date"), sp_st_date(d.dates.operation_date)],
				[__("Technically Closed On"), sp_st_date(d.dates.tech_closed_on)],
				[__("Financially Closed On"), sp_st_date(d.dates.fin_closed_on)],
			]) +
			sp_st_h(__("Timeline")) +
			timeline +
			sp_st_h(__("Open Tasks")) +
			sp_st_table(
				[
					{ label: __("Task"), key: "subject" },
					{ label: __("Assigned To"), key: "assigned_to_name" },
					{ label: __("Due"), key: "due_at", type: "date" },
				],
				d.tasks,
				amounts,
				__("No open tasks.")
			)
		);
	},

	scope(d, amounts) {
		return (
			sp_st_h(__("Quantities from the accepted quote {0}", [d.quote || ""])) +
			sp_st_table(
				[
					{ label: __("Item Code"), key: "item_code" },
					{ label: __("Item Name"), key: "item_name" },
					{ label: __("Qty"), key: "qty" },
					{ label: __("UOM"), key: "uom" },
				],
				d.lines,
				amounts,
				__("No accepted quote yet.")
			) +
			sp_st_h(__("Returns from the site")) +
			sp_st_table(
				[
					{ label: __("Stock Entry"), key: "name", type: "link", doctype: "Stock Entry" },
					{ label: __("Date"), key: "posting_date", type: "date" },
					{ label: __("Status"), key: "sp_return_status", type: "status" },
				],
				d.returns,
				amounts,
				__("No returns.")
			) +
			sp_st_h(__("Change Orders")) +
			sp_st_table(
				[
					{ label: __("Change Order"), key: "name", type: "link", doctype: "SP Change Order" },
					{ label: __("Date"), key: "posting_date", type: "date" },
					{
						label: __("Lines"),
						value: (r) => r.lines.map((l) => `${l.item_name || l.item_code} ${l.qty > 0 ? "+" : ""}${l.qty}`).join("، "),
					},
					{ label: __("Change"), key: "delta_amount", type: "money" },
					{ label: __("Reason"), key: "reason" },
					{ label: __("Status"), value: (r) => (r.docstatus ? "Submitted" : "Draft"), type: "status" },
				],
				d.change_orders,
				amounts,
				__("No change orders.")
			)
		);
	},

	agreement(d, amounts) {
		if (!d.contract) return `<p class="text-muted">${__("No contract yet.")}</p>`;
		const pdf = `<a class="btn btn-xs btn-default" href="${encodeURI(d.pdf)}" target="_blank" rel="noopener">${__("Contract PDF")}</a>`;
		return (
			`<p class="text-muted small">${__("Read-only after signing: it changes only through a change order.")}</p>` +
			sp_st_facts([
				[__("Contract"), `<a href="/app/sales-order/${encodeURIComponent(d.contract)}">${sp_st_esc(d.contract)}</a> ${pdf}`],
				[__("Contract Date"), sp_st_date(d.date)],
				[__("Status"), sp_st_esc(d.signed ? __("Signed") : __("Draft"))],
				[__("Financing"), sp_st_esc(d.financing)],
				[__("Bank Branch"), sp_st_esc(d.bank_branch)],
				[__("Discount"), amounts && d.discount_amount ? `${sp_st_money(d.discount_amount)} (${sp_st_esc(d.discount_pct || 0)}%)` : ""],
				[__("Total"), amounts ? sp_st_money(d.total) : ""],
			]) +
			sp_st_h(__("Agreed Lines")) +
			sp_st_table(
				[
					{ label: __("Item Code"), key: "item_code" },
					{ label: __("Item Name"), key: "item_name" },
					{ label: __("Qty"), key: "qty" },
					{ label: __("Rate"), key: "rate", type: "money" },
					{ label: __("Amount"), key: "amount", type: "money" },
				],
				d.lines,
				amounts
			) +
			sp_st_h(__("Payment Terms")) +
			sp_st_table(
				[
					{ label: __("Due Date"), key: "due_date", type: "date" },
					{ label: __("Description"), key: "description" },
					{ label: __("Amount"), key: "amount", type: "money" },
				],
				d.terms,
				amounts
			)
		);
	},

	payments(d, amounts) {
		const pay_cols = [
			{ label: __("Payment"), key: "name", type: "link", doctype: "SP Customer Payment" },
			{ label: __("Date"), key: "work_date", type: "date" },
			{ label: __("Amount"), key: "amount", type: "money" },
			{ label: __("Method"), key: "method" },
			{ label: __("Channel"), value: (r) => __(r.channel) },
			{ label: __("Status"), key: "status", type: "status" },
			{ label: __("Recorded By"), key: "recorded_by_name" },
		];
		return (
			sp_st_h(__("Payment Schedule")) +
			sp_st_table(
				[
					{ label: __("Due Date"), key: "due_date", type: "date" },
					{ label: __("Amount"), key: "amount", type: "money" },
					{ label: __("Paid"), key: "paid", type: "money" },
					{ label: __("Status"), key: "status", type: "status" },
				],
				d.schedule,
				amounts,
				__("No payment schedule.")
			) +
			sp_st_h(__("Customer Payments")) +
			sp_st_table(pay_cols, d.payments, amounts, __("No payments yet.")) +
			sp_st_h(__("Paid to Third Parties from the Customer's Money")) +
			sp_st_table(
				[...pay_cols, { label: __("Paid To"), value: (r) => `${__(r.third_party_type)}: ${r.third_party}` }],
				d.third_party,
				amounts,
				__("None.")
			) +
			sp_st_h(__("Cheques")) +
			sp_st_table(
				[
					{ label: __("Cheque No"), key: "cheque_no" },
					{ label: __("Amount"), key: "amount", type: "money" },
					{ label: __("Due Date"), key: "due_date", type: "date" },
					{ label: __("Status"), key: "status", type: "status" },
					{ label: __("Holder"), key: "holder_name" },
					{ label: __("Bank or Post"), key: "bank_or_post" },
				],
				d.cheques,
				amounts,
				__("No cheques.")
			) +
			sp_st_h(__("Agri Bank Advance")) +
			sp_st_table(
				[
					{ label: __("Advance"), key: "name", type: "link", doctype: "SP Customer Advance" },
					{ label: __("Status"), key: "status", type: "status" },
					{ label: __("Bank"), key: "bank" },
					{ label: __("Amount"), key: "amount", type: "money" },
					{ label: __("Repaid"), key: "repaid_amount", type: "money" },
					{ label: __("Outstanding"), key: "outstanding_amount", type: "money" },
				],
				d.advances,
				amounts,
				__("None.")
			)
		);
	},

	purchasing(d, amounts) {
		return (
			sp_st_h(__("Purchase Orders")) +
			sp_st_table(
				[
					{ label: __("Purchase Order"), key: "name", type: "link", doctype: "Purchase Order" },
					{ label: __("Supplier"), key: "supplier_name" },
					{ label: __("Date"), key: "transaction_date", type: "date" },
					{ label: __("Status"), value: (r) => __(r.sp_status) },
					{ label: __("Destination"), value: (r) => __(r.sp_destination_type) },
					{ label: __("Next Delivery"), key: "sp_next_delivery", type: "date" },
					...(d.supplier_prices ? [{ label: __("Total"), key: "grand_total", type: "money" }] : []),
				],
				d.orders,
				amounts,
				__("No purchase orders yet.")
			) +
			sp_st_h(__("Receipts")) +
			sp_st_table(
				[
					{ label: __("Receipt"), key: "name", type: "link", doctype: "Purchase Receipt" },
					{ label: __("Date"), key: "posting_date", type: "date" },
					{ label: __("Purchase Order"), key: "sp_purchase_order" },
					{ label: __("Received At"), key: "set_warehouse" },
					{ label: __("Status"), value: (r) => __(r.sp_receipt_status) },
				],
				d.receipts,
				amounts,
				__("Nothing received yet.")
			) +
			sp_st_h(__("Consignment Withdrawals")) +
			sp_st_table(
				[
					{ label: __("Date"), key: "movement_date", type: "date" },
					{ label: __("Movement"), value: (r) => __(r.movement_type) },
					{ label: __("Item"), key: "item" },
					{ label: __("Qty"), key: "qty" },
					{ label: __("Status"), key: "status", type: "status" },
				],
				d.consignment,
				amounts,
				__("None.")
			) +
			sp_st_h(__("Transfers to the Site")) +
			sp_st_table(
				[
					{ label: __("Transfer"), key: "name", type: "link", doctype: "Material Request" },
					{ label: __("Date"), key: "transaction_date", type: "date" },
					{ label: __("Transfer From"), value: (r) => __(r.sp_source_kind) },
					{ label: __("Transport"), value: (r) => __(r.sp_transport) },
					{ label: __("Status"), value: (r) => __(r.sp_transfer_status) },
				],
				d.transfers,
				amounts,
				__("No transfers yet.")
			) +
			sp_st_h(__("Stock Moves: Transfers In, Consumption and Returns")) +
			sp_st_table(
				[
					{ label: __("Stock Entry"), key: "name", type: "link", doctype: "Stock Entry" },
					{ label: __("Date"), key: "posting_date", type: "date" },
					{ label: __("Type"), value: (r) => __(r.stock_entry_type || r.purpose) },
					{ label: __("Return"), value: (r) => (r.sp_return_status ? __(r.sp_return_status) : "") },
				],
				d.stock_entries,
				amounts,
				__("None.")
			)
		);
	},

	site(d, amounts) {
		return (
			sp_st_facts([
				[__("Site Receiver"), sp_st_esc(d.site_receiver)],
				[__("Daily Labour"), amounts && d.labour_total ? sp_st_money(d.labour_total) : ""],
			]) +
			sp_st_h(__("Tasks")) +
			sp_st_table(
				[
					{ label: __("Task"), key: "subject" },
					{ label: __("Status"), key: "status", type: "status" },
					{ label: __("Assigned To"), key: "assigned_to_name" },
					{ label: __("Due"), key: "due_at", type: "date" },
				],
				d.tasks,
				amounts,
				__("No tasks.")
			) +
			sp_st_h(__("Site Daily Logs")) +
			sp_st_table(
				[
					{ label: __("Log"), key: "name", type: "link", doctype: "SP Site Daily Log" },
					{ label: __("Date"), key: "work_date", type: "date" },
					{ label: __("Crew"), key: "crew" },
					{ label: __("Labour"), key: "labour_total", type: "money" },
					{ label: __("Issues"), key: "issues" },
					{ label: __("Logged By"), key: "logged_by" },
				],
				d.logs,
				amounts,
				__("No site logs yet.")
			) +
			sp_st_h(__("Winch and Car Jobs")) +
			sp_st_table(
				[
					{ label: __("Job"), key: "name", type: "link", doctype: "SP Field Entry" },
					{ label: __("Date"), key: "work_date", type: "date" },
					{ label: __("Vehicle"), key: "vehicle" },
					{ label: __("Job Type"), key: "job_type" },
					{ label: __("Hours"), key: "hours" },
					{ label: __("Days"), key: "days" },
					{ label: __("Agreed"), key: "agreed_amount", type: "money" },
					{ label: __("Status"), key: "status", type: "status" },
				],
				d.jobs,
				amounts,
				__("No jobs yet.")
			) +
			sp_st_h(__("Booked Jobs")) +
			sp_st_table(
				[
					{ label: __("Booking"), key: "name", type: "link", doctype: "SP Vehicle Booking" },
					{ label: __("Planned Date"), key: "planned_date", type: "date" },
					{ label: __("Vehicle"), key: "vehicle" },
					{ label: __("Job Type"), key: "job_type" },
					{ label: __("Agreed"), key: "agreed_amount", type: "money" },
					{ label: __("Status"), value: (r) => __(r.status) },
				],
				d.bookings,
				amounts,
				__("None.")
			) +
			sp_st_h(__("Site Expenses")) +
			sp_st_table(
				[
					{ label: __("Date"), key: "work_date", type: "date" },
					{ label: __("Expense Type"), key: "expense_type" },
					{ label: __("Amount"), key: "amount", type: "money" },
					{ label: __("Status"), key: "status", type: "status" },
					{ label: __("Note"), key: "note" },
				],
				d.expenses,
				amounts,
				__("No site expenses.")
			)
		);
	},

	programming(d, amounts) {
		if (!d.commissionings.length) return `<p class="text-muted">${__("Not programmed yet.")}</p>`;
		return d.commissionings
			.map(
				(c) =>
					`<div class="border rounded p-3 mb-3">` +
					sp_st_facts([
						[__("Commissioning"), `<a href="/app/sp-commissioning/${encodeURIComponent(c.name)}">${sp_st_esc(c.name)}</a>`],
						[__("Status"), sp_st_esc(c.docstatus ? __("Submitted") : __("Draft"))],
						[__("System"), sp_st_esc(c.system_type)],
						[__("Inverter"), sp_st_esc([c.inverter_brand, c.inverter_model].filter(Boolean).join(" "))],
						[__("Inverter Serial"), sp_st_esc(c.inverter_serial)],
						[__("Remote Support ID"), sp_st_esc(c.remote_support_id)],
						[
							__("Settings File"),
							c.settings?.file
								? `<a href="${encodeURI(c.settings.file)}" target="_blank" rel="noopener">${sp_st_esc(c.settings.title)} (v${sp_st_esc(c.settings.version)})</a>`
								: "",
						],
						[__("Operation Date"), sp_st_date(c.operation_date)],
					]) +
					sp_st_table(
						[
							{ label: __("Reading"), key: "param" },
							{ label: __("Value"), key: "value" },
							{ label: __("Unit"), key: "unit" },
						],
						c.readings,
						amounts,
						__("No test readings.")
					) +
					`</div>`
			)
			.join("");
	},

	documents(d, amounts) {
		let html =
			sp_st_h(__("Files on the Station")) +
			sp_st_table(
				[
					{ label: __("File"), key: "file_url", type: "file", text: (r) => r.file_name },
					{ label: __("Added By"), key: "uploaded_by" },
					{ label: __("Date"), key: "creation", type: "date" },
				],
				d.files,
				amounts,
				__("No files yet. Attach them from the sidebar.")
			);
		if (!amounts) return html;
		html +=
			sp_st_h(__("Quote Versions")) +
			sp_st_table(
				[
					{ label: __("Quote"), key: "name", type: "link", doctype: "Quotation" },
					{ label: __("Version"), key: "sp_version" },
					{ label: __("Option"), key: "sp_option_label" },
					{ label: __("Status"), value: (r) => __(r.sp_status) },
					{ label: __("Date"), key: "transaction_date", type: "date" },
					{ label: __("Total"), key: "grand_total", type: "money" },
				],
				d.quotes,
				amounts,
				__("None.")
			);
		if (d.contract) {
			html +=
				sp_st_h(__("Contract")) +
				`<p><a href="/app/sales-order/${encodeURIComponent(d.contract.name)}">${sp_st_esc(d.contract.name)}</a> · <a href="${encodeURI(d.contract.pdf)}" target="_blank" rel="noopener">${__("Contract PDF")}</a></p>`;
		}
		return (
			html +
			sp_st_h(__("Invoices")) +
			sp_st_table(
				[
					{ label: __("Invoice"), key: "name", type: "link", doctype: "Sales Invoice" },
					{ label: __("Date"), key: "posting_date", type: "date" },
					{ label: __("Total"), key: "grand_total", type: "money" },
					{ label: __("Status"), value: (r) => __(r.status) },
				],
				d.invoices,
				amounts,
				__("No invoices yet.")
			)
		);
	},

	warranty(d, amounts) {
		return (
			sp_st_facts([[__("Operation Date"), sp_st_date(d.operation_date)]]) +
			sp_st_h(__("Component Warranties")) +
			sp_st_table(
				[
					{ label: __("Component"), value: (r) => __(r.component_type) },
					{ label: __("Item"), key: "item_name" },
					{ label: __("Serial No"), key: "serial" },
					{ label: __("Warranty (months)"), key: "warranty_months" },
					{ label: __("Warranty Ends"), key: "warranty_end", type: "date" },
					{ label: __("Status"), value: (r) => (r.active ? "Active" : "Expired"), type: "status" },
				],
				d.components,
				amounts,
				__("The warranties start when the station is commissioned.")
			) +
			`<p class="text-muted small">${__("Service tickets and supplier claims are added here when the service screens are built.")}</p>`
		);
	},

	costs(d) {
		const labels = {
			purchases: __("Purchases"),
			consignment: __("Consignment goods"),
			materials: __("Materials used, showroom goods at cost"),
			winch: __("Winch and car jobs"),
			custody: __("Custody and site spending"),
			labour: __("Daily labour"),
			commission: __("Referrer commission"),
			other: __("Other"),
			indirect: __("Indirect share"),
		};
		const profit = (v) => `<span class="${v < 0 ? "text-danger" : "text-success"}">${sp_st_money(v)}</span>`;
		return (
			sp_st_facts([
				[__("Agreed"), sp_st_money(d.agreed)],
				[__("Estimated Cost (frozen)"), `${sp_st_money(d.estimated)}${d.frozen_on ? ` <span class="text-muted small">${sp_st_date(d.frozen_on)}</span>` : ""}`],
				[__("Actual Cost"), `${sp_st_money(d.actual)} <span class="text-muted small">${__("incl. indirect {0}", [sp_st_money(d.indirect)])}</span>`],
				[__("Expected Profit"), profit(d.expected_profit)],
				[__("Actual Profit"), profit(d.actual_profit)],
			]) +
			sp_st_h(__("Actual Cost by Source")) +
			sp_st_table(
				[
					{ label: __("Source"), value: (r) => labels[r.source] || r.source },
					{ label: __("Amount"), key: "amount", type: "money" },
				],
				d.lines,
				true,
				__("Nothing posted on this station yet.")
			)
		);
	},

	history(d, amounts) {
		return (
			sp_st_h(__("Field Changes")) +
			sp_st_table(
				[
					{ label: __("When"), key: "when", type: "date" },
					{ label: __("By"), key: "by" },
					{ label: __("Field"), key: "field" },
					{ label: __("From"), key: "old" },
					{ label: __("To"), key: "new" },
				],
				d.changes,
				amounts,
				__("No changes yet.")
			)
		);
	},
};

// --- the next step, by status (SP-76) ------------------------------------------------------------

async function sp_station_next_step(frm) {
	const { status } = frm.doc;
	const buying = ["Open", "Purchasing"].includes(status);
	if (buying && frappe.model.can_create("Purchase Order")) {
		frm.add_custom_button(__("Create Purchase Order"), () =>
			frappe.new_doc("Purchase Order", { sp_station: frm.doc.name, project: frm.doc.project, sp_destination_type: "Site" })
		);
		if (status === "Open") frm.change_custom_button_type(__("Create Purchase Order"), null, "primary");
	}
	if (buying && SP_ST_TRANSFER_ROLES.some((r) => frappe.user.has_role(r))) {
		frm.add_custom_button(__("Create Transfer"), () => {
			frappe.route_options = { sp_new_transfer: frm.doc.name };
			frappe.set_route("sp-transfers");
		});
	}
	const next = SP_ST_NEXT[status];
	if (!next || status === "Open") return;
	const transitions = await frappe.xcall("frappe.model.workflow.get_transitions", { doc: frm.doc });
	if (!transitions.some((t) => t.action === next) || frm.doc.status !== status) return;
	frm.add_custom_button(__(next), () =>
		frappe.confirm(__("{0} for station {1}?", [__(next), frm.doc.name]), async () => {
			await frappe.xcall("frappe.model.workflow.apply_workflow", { doc: frm.doc, action: next });
			frm.reload_doc();
		})
	);
	frm.change_custom_button_type(__(next), null, "primary");
}
