// C2 customer record (SP-50): the customer before the call. Five tabs from
// smart_power.sp_sales.customer_360 (sale prices only, never cost): Overview, Requests and
// Quotes, Calls, Stations (read-only), Documents. "Log call" opens F3 on the active case;
// "New request" opens C3 with the customer's mobile.
frappe.ui.form.on("Customer", {
	async refresh(frm) {
		if (frm.is_new() || !frm.fields_dict.sp_overview_html) return;
		const { message: v } = await frappe.call("smart_power.sp_sales.customer_360.customer_360", {
			customer: frm.doc.name,
		});
		frm.sp_360 = v;
		sp_customer.render(frm, v);
		if (v.can_log_call) {
			frm.add_custom_button(__("Log call"), () =>
				sp.sales.log_call_dialog(v.active_case, () => frm.reload_doc())
			);
		}
		if (v.can_request && frm.doc.sp_mobile) {
			frm.add_custom_button(__("New request"), () => {
				frappe.route_options = { mobile: frm.doc.sp_mobile };
				frappe.set_route("sp-quote-request");
			});
		}
		if (!frm.sp_tab_opened) {
			frm.sp_tab_opened = true; // the overview first, once per form
			frm.layout.select_tab("sp_overview_tab");
		}
	},
});

const sp_customer = {
	esc: (v) => frappe.utils.escape_html(v == null ? "" : String(v)),
	money: (v) => frappe.utils.escape_html(format_currency(v || 0)),
	date: (v) => frappe.utils.escape_html(v ? frappe.datetime.str_to_user(v) : ""),
	link: (doctype, name, label) =>
		`<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${sp_customer.esc(label || name)}</a>`,
	table(head, rows, empty) {
		const esc = sp_customer.esc;
		if (!rows.length) return `<p class="text-muted">${esc(empty)}</p>`;
		return `<table class="table table-sm sp-360-table"><thead><tr>${head
			.map((h) => `<th>${esc(h)}</th>`)
			.join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
	},

	render(frm, v) {
		const html = (field, content) => frm.fields_dict[field] && frm.fields_dict[field].$wrapper.html(content);
		html("sp_overview_html", this.overview(v));
		html("sp_requests_html", this.requests(v));
		html("sp_calls_html", this.calls(v));
		html("sp_stations_html", this.stations(v));
		html("sp_documents_html", this.documents(v));
	},

	overview(v) {
		const o = v.overview;
		const esc = this.esc;
		const item = (label, value) =>
			`<div class="col-sm-4 mb-3"><div class="text-muted small">${esc(label)}</div><div>${value}</div></div>`;
		const last = o.last_call
			? `${esc(o.last_call.result_label)} · ${this.date(o.last_call.call_time)} · ${esc(o.last_call.logged_by_name)}`
			: esc(__("No call yet."));
		return `<div class="sp-360-overview">
			${o.featured ? `<div class="mb-2"><span class="indicator-pill yellow">${esc(__("★ Featured"))}</span></div>` : ""}
			<div class="row">
				${item(__("Customer"), `<b>${esc(o.customer_name)}</b>`)}
				${item(__("Mobile"), esc([o.mobile, o.mobile_2].filter(Boolean).join(" · ")))}
				${item(__("Follow-up Owner"), esc(o.owner_name || "—"))}
				${item(__("Tier"), esc(o.tier ? __(o.tier) : "—"))}
				${item(__("Region"), esc(o.region || "—"))}
				${item(__("Last Call"), last)}
				${item(__("Open Cases"), esc(o.open_cases))}
				${item(__("Won"), esc(o.won_cases))}
				${item(__("Lost"), esc(o.lost_cases))}
				${item(__("Agreed"), this.money(o.agreed))}
				${item(__("Paid"), this.money(o.paid))}
				${item(__("Remaining"), this.money(o.remaining))}
			</div></div>`;
	},

	requests(v) {
		const esc = this.esc;
		if (!v.cases.length) return `<p class="text-muted">${esc(__("No request yet."))}</p>`;
		return v.cases
			.map((c) => {
				const quotes = v.quotes.filter((q) => q.sp_case === c.name);
				const rows = quotes.map((q) => [
					this.link("Quotation", q.name, `${q.sp_option_label || "A"} · v${q.sp_version}`),
					`${esc(__(q.sp_status || ""))}${q.sp_is_approved ? " ✓" : ""}`,
					this.date(q.transaction_date),
					esc(format_currency(q.grand_total, q.currency)),
				]);
				const head = `${this.link("SP Case", c.name)} · ${esc(c.system_type || "")} · <b>${esc(__(c.status))}</b>
					${c.lost_reason ? ` · ${esc(c.lost_reason)}` : ""} · ${this.date(c.creation)}
					${c.indicative_price ? ` · ${esc(__("Indicative Price"))}: ${this.money(c.indicative_price)}` : ""}`;
				return `<div class="mb-3"><div class="mb-1">${head}</div>${this.table(
					[__("Version"), __("Status"), __("Date"), __("Sale Total")],
					rows,
					__("No quote yet.")
				)}</div>`;
			})
			.join("");
	},

	calls(v) {
		const esc = this.esc;
		return this.table(
			[__("Date"), __("Result"), __("Note"), __("By"), __("Case")],
			v.calls.map((c) => [
				this.date(c.call_time),
				esc(c.result_label),
				esc(c.note || ""),
				esc(c.logged_by_name || ""),
				this.link("SP Case", c.case),
			]),
			__("No call yet.")
		);
	},

	stations(v) {
		const esc = this.esc;
		return this.table(
			[__("Station"), __("Status"), __("Agreed"), __("Paid"), __("Remaining")],
			v.stations.map((s) => [
				this.link("SP Station", s.name),
				esc(__(s.status)),
				this.money(s.agreed_amount),
				this.money(s.paid_amount),
				this.money(s.remaining_amount),
			]),
			__("No station yet.")
		);
	},

	documents(v) {
		const esc = this.esc;
		return this.table(
			[__("File"), __("Attached To"), __("Date")],
			v.documents.map((f) => [
				`<a href="${encodeURI(f.file_url)}" target="_blank" rel="noopener">${esc(f.file_name)}</a>`,
				this.link(f.attached_to_doctype, f.attached_to_name, `${__(f.attached_to_doctype)} ${f.attached_to_name}`),
				this.date(f.creation),
			]),
			__("No document yet.")
		);
	},
};
