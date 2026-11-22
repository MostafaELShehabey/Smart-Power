// X13 Audit log (SP-137): who did what and when, from the audit log, edits with a reason, rule
// overrides, the sensitive records' field changes, exports and deletes. Filter by user, record or
// date, and export. The rows come from smart_power.sp_core.audit_trail.
const SP_AT_API = "smart_power.sp_core.audit_trail";

frappe.pages["sp-audit-trail"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Audit Log"), single_column: true });
	frappe.pages["sp-audit-trail"].sp_audit_trail = new SPAuditTrail(page);
};

frappe.pages["sp-audit-trail"].on_page_show = function () {
	const page = frappe.pages["sp-audit-trail"].sp_audit_trail;
	const options = frappe.route_options || {};
	frappe.route_options = null;
	if (!page) return;
	page.quiet = true; // one refresh for all the filters the link sets
	for (const key of ["doctype", "name", "user"]) if (options[key]) page.filters[key].set_input(options[key]);
	page.quiet = false;
	page.refresh();
};

class SPAuditTrail {
	constructor(page) {
		this.page = page;
		const change = () => !this.quiet && this.refresh();
		this.filters = {
			user: page.add_field({ fieldname: "user", fieldtype: "Link", options: "User", label: __("User"), change }),
			doctype: page.add_field({ fieldname: "doctype", fieldtype: "Link", options: "DocType", label: __("Document Type"), change }),
			name: page.add_field({ fieldname: "name", fieldtype: "Data", label: __("Record"), change }),
			from_date: page.add_field({ fieldname: "from_date", fieldtype: "Date", label: __("From"), change }),
			to_date: page.add_field({ fieldname: "to_date", fieldtype: "Date", label: __("To"), change }),
		};
		page.set_primary_action(__("Export"), () => this.export());
		this.$body = $('<div class="sp-at-body"></div>').appendTo(page.main);
		this.refresh();
	}

	values() {
		const out = {};
		for (const [k, f] of Object.entries(this.filters)) if (f.get_value()) out[k] = f.get_value();
		return out;
	}

	async refresh() {
		const asked = (this.asked = (this.asked || 0) + 1);
		const { message } = await frappe.call(`${SP_AT_API}.rows`, { filters: this.values() });
		if (asked !== this.asked) return; // a later refresh is on its way
		this.rows = message || [];
		this.render();
	}

	render() {
		const esc = frappe.utils.escape_html;
		if (!this.rows.length) {
			this.$body.html(`<div class="text-muted">${esc(__("Nothing in the log for these filters."))}</div>`);
			return;
		}
		const body = this.rows
			.map((r) => {
				const link = r.reference_name
					? `<a href="/app/${frappe.router.slug(r.reference_doctype)}/${encodeURIComponent(r.reference_name)}">${esc(
							r.reference_name
						)}</a>`
					: "";
				return `<tr><td class="text-nowrap">${esc(frappe.datetime.str_to_user(r.at))}</td>
					<td>${esc((frappe.user_info(r.user) || {}).fullname || r.user || "")}</td><td>${esc(r.action)}</td>
					<td>${esc(__(r.reference_doctype || ""))}</td><td>${link}</td>
					<td class="small">${esc(r.details || "")}</td><td class="small text-muted">${esc(r.ip || "")}</td></tr>`;
			})
			.join("");
		this.$body.html(`<table class="table table-sm"><thead><tr><th>${esc(__("Time"))}</th><th>${esc(__("User"))}</th>
			<th>${esc(__("Action"))}</th><th>${esc(__("Document Type"))}</th><th>${esc(__("Record"))}</th>
			<th>${esc(__("Details"))}</th><th>${esc(__("IP Address"))}</th></tr></thead><tbody>${body}</tbody></table>
			<div class="small text-muted">${esc(__("The log is append-only: nobody edits or deletes it."))}</div>`);
	}

	async export() {
		const { message } = await frappe.call({ method: `${SP_AT_API}.export`, args: { filters: this.values() } });
		const head = [__("Time"), __("User"), __("Action"), __("Document Type"), __("Record"), __("Details"), __("IP Address")];
		const data = [head].concat(
			(message || []).map((r) => [r.at, r.user, r.action, r.reference_doctype, r.reference_name, r.details, r.ip])
		);
		frappe.tools.downloadify(data, null, __("Audit Log"));
	}
}
