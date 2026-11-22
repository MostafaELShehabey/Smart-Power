// RV2 Review centre (SP-129): everything outside the normal path, by tab, for the admin to review
// after the fact. Per item: open the record, comment to its owner (notified with a link),
// forward to another reviewer, mark reviewed; several at once with the checkboxes.
// The rules are on the server (smart_power.sp_core.review_centre).

const SP_RV_API = "smart_power.sp_core.review_centre";

frappe.pages["sp-review-centre"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Review Centre"),
		single_column: true,
	});
	wrapper.sp_review_centre = new SPReviewCentre(page);
};

frappe.pages["sp-review-centre"].on_page_show = function (wrapper) {
	// AD1 opens a tab here (SP-138)
	const category = frappe.route_options && frappe.route_options.category;
	frappe.route_options = null;
	if (!wrapper.sp_review_centre) return;
	if (category) wrapper.sp_review_centre.category = category;
	wrapper.sp_review_centre.refresh();
};

class SPReviewCentre {
	constructor(page) {
		this.page = page;
		this.category = null;
		this.status = "Open";
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$bulk = this.page.add_inner_button(__("Mark selected reviewed"), () => this.mark_selected());
		this.status_field = this.page.add_field({
			fieldname: "status",
			fieldtype: "Select",
			label: __("Status"),
			options: [
				{ value: "Open", label: __("Open") },
				{ value: "Reviewed", label: __("Reviewed") },
			],
			default: "Open",
			change: () => {
				this.status = this.status_field.get_value() || "Open";
				this.load_items();
			},
		});
		this.$tabs = $('<div class="sp-rv-tabs mb-3"></div>').appendTo(this.page.main);
		this.$body = $('<div class="sp-rv-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_RV_API}.tabs`);
		this.tabs = message.tabs;
		if (!this.category) {
			const first = this.tabs.find((t) => t.open) || this.tabs[0];
			this.category = first.category;
		}
		this.render_tabs();
		this.load_items();
	}

	render_tabs() {
		const esc = frappe.utils.escape_html;
		this.$tabs.empty();
		this.tabs.forEach((tab) => {
			const highlighted = tab.highlighted
				? ` <span class="indicator-pill red">${esc(String(tab.highlighted))}</span>`
				: "";
			$(`<button class="btn btn-sm ${tab.category === this.category ? "btn-primary" : "btn-default"} mb-1 mr-1">
				${esc(tab.label)} <span class="badge">${esc(String(tab.open))}</span>${highlighted}
			</button>`)
				.on("click", () => {
					this.category = tab.category;
					this.render_tabs();
					this.load_items();
				})
				.appendTo(this.$tabs);
		});
	}

	async load_items() {
		const { message: rows } = await frappe.call(`${SP_RV_API}.items`, {
			category: this.category,
			status: this.status,
		});
		this.rows = rows || [];
		this.render_items();
	}

	render_items() {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		this.$bulk.toggle(this.status === "Open");
		if (!this.rows.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("Nothing to review here."))}</div>`);
			return;
		}
		const open = this.status === "Open";
		const $table = $(`<table class="table table-hover sp-rv-table"><thead><tr>
			${open ? '<th><input type="checkbox" class="sp-rv-all"></th>' : ""}
			<th>${esc(__("Record"))}</th><th>${esc(__("Summary"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Raised By"))}</th>
			<th>${esc(__("Owner"))}</th><th>${esc(__("Comment"))}</th><th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		this.rows.forEach((row) => {
			const route = row.reference_doctype
				? `/app/${frappe.router.slug(row.reference_doctype)}/${encodeURIComponent(row.reference_name)}`
				: "";
			const $tr = $(`<tr class="${row.highlight ? "sp-rv-highlight" : ""}" data-name="${esc(row.name)}">
				${open ? `<td><input type="checkbox" class="sp-rv-check" value="${esc(row.name)}"></td>` : ""}
				<td>${
					route ? `<a href="${route}">${esc(row.reference_name)}</a>` : esc(row.reference_name || "")
				}<div class="small text-muted">${esc(__(row.reference_doctype || ""))}</div></td>
				<td>${row.highlight ? '<span class="indicator-pill red mr-1">!</span>' : ""}${esc(
				row.summary || ""
			)}${row.reason ? `<div class="small text-muted">${esc(__("Reason"))}: ${esc(row.reason)}</div>` : ""}</td>
				<td class="text-right">${row.amount ? esc(format_currency(row.amount)) : ""}</td>
				<td>${esc(row.raised_by_name || "")}<div class="small text-muted">${esc(
				frappe.datetime.str_to_user(row.creation)
			)}</div></td>
				<td>${esc(row.owner_name || "")}</td>
				<td>${esc(row.comment || "")}</td>
				<td class="text-nowrap"></td>
			</tr>`).appendTo($table.find("tbody"));
			const $actions = $tr.find("td:last");
			if (open) {
				this.action($actions, __("Comment"), () => this.comment_dialog(row));
				this.action($actions, __("Forward"), () => this.forward_dialog(row));
				this.action($actions, __("Reviewed"), () => this.mark([row.name]), "btn-primary");
			}
		});
		$table.find(".sp-rv-all").on("change", (e) =>
			$table.find(".sp-rv-check").prop("checked", e.target.checked)
		);
	}

	action($cell, label, handler, style = "btn-default") {
		$(`<button class="btn btn-xs ${style} mr-1"></button>`).text(label).on("click", handler).appendTo($cell);
	}

	async mark(names, comment) {
		const { message: done } = await frappe.call({
			method: `${SP_RV_API}.mark_reviewed`,
			args: { names, comment },
			freeze: true,
		});
		frappe.show_alert({ message: __("{0} marked reviewed.", [done]), indicator: "green" });
		this.refresh();
	}

	mark_selected() {
		const names = this.$body
			.find(".sp-rv-check:checked")
			.map((_, el) => el.value)
			.get();
		if (!names.length) {
			frappe.msgprint(__("Select the items to mark reviewed."));
			return;
		}
		frappe.confirm(__("Mark {0} items reviewed?", [names.length]), () => this.mark(names));
	}

	comment_dialog(row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Comment to the owner"),
			fields: [
				{
					fieldname: "to_user",
					fieldtype: "Link",
					options: "User",
					label: __("To"),
					default: row.owner,
				},
				{ fieldname: "comment", fieldtype: "Small Text", label: __("Comment"), reqd: 1 },
			],
			primary_action_label: __("Send"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_RV_API}.comment`,
					args: { name: row.name, ...values },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("The owner is notified."), indicator: "green" });
				this.load_items();
			},
		});
		dialog.show();
	}

	forward_dialog(row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Forward"),
			fields: [
				{ fieldname: "to_user", fieldtype: "Link", options: "User", label: __("To"), reqd: 1 },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Forward"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_RV_API}.forward`,
					args: { name: row.name, ...values },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Forwarded."), indicator: "green" });
			},
		});
		dialog.show();
	}
}

$(`<style>
	.sp-rv-highlight { background: var(--bg-red); }
</style>`).appendTo(document.head);
