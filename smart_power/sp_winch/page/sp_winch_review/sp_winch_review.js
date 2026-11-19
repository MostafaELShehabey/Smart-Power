// RV1 Field review (SP-110): the operators' entries by work date and vehicle, with their flags.
// Per entry: complete what is missing (with a reason), mark reviewed, flag abnormal for the admin.
// Per day: mark it all reviewed (a green check once every entry is), reopen a locked vehicle-day.
// The rules are on the server (smart_power.sp_winch.review).

const SP_FR_API = "smart_power.sp_winch.review";
// how each detail the operator may leave out is asked for in the complete dialog
const SP_FR_FIELDS = {
	place: { fieldtype: "Data", label: __("Place") },
	agreed_amount: { fieldtype: "Currency", label: __("Agreed Amount") },
	photo: { fieldtype: "Attach Image", label: __("Photo") },
};

frappe.pages["sp-winch-review"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Field Review"),
		single_column: true,
	});
	wrapper.sp_winch_review = new SPFieldReview(page);
};

frappe.pages["sp-winch-review"].on_page_show = function (wrapper) {
	wrapper.sp_winch_review && wrapper.sp_winch_review.load();
};

class SPFieldReview {
	constructor(page) {
		this.page = page;
		this.flag = null;
		this.page.add_inner_button(__("Refresh"), () => this.load());
		const field = (df) => this.page.add_field({ ...df, change: () => this.load() });
		this.from_date = field({
			fieldname: "from_date",
			fieldtype: "Date",
			label: __("From"),
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -6),
		});
		this.to_date = field({
			fieldname: "to_date",
			fieldtype: "Date",
			label: __("To"),
			default: frappe.datetime.get_today(),
		});
		this.vehicle = field({
			fieldname: "vehicle",
			fieldtype: "Link",
			options: "Vehicle",
			label: __("Vehicle"),
		});
		this.to_review = field({
			fieldname: "to_review",
			fieldtype: "Check",
			label: __("Not reviewed only"),
		});
		this.$chips = $('<div class="sp-fr-chips mb-3"></div>').appendTo(this.page.main);
		this.$body = $('<div class="sp-fr-body"></div>').appendTo(this.page.main);
	}

	async load() {
		const { message } = await frappe.call(`${SP_FR_API}.entries`, {
			from_date: this.from_date.get_value(),
			to_date: this.to_date.get_value(),
			vehicle: this.vehicle.get_value(),
			flag: this.flag,
			to_review: this.to_review.get_value() ? 1 : 0,
		});
		this.data = message;
		this.render_chips();
		this.render_days();
	}

	render_chips() {
		const esc = frappe.utils.escape_html;
		this.$chips.empty();
		const chip = (flag, label, count) =>
			$(`<button class="btn btn-sm ${this.flag === flag ? "btn-primary" : "btn-default"} mb-1 mr-1">
				${esc(label)}${count === null ? "" : ` <span class="badge">${esc(String(count))}</span>`}
			</button>`)
				.on("click", () => {
					this.flag = flag;
					this.load();
				})
				.appendTo(this.$chips);
		chip(null, __("All"), null);
		this.data.flags.forEach((f) => chip(f.flag, f.label, f.count));
	}

	render_days() {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		if (!this.data.days.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("No entries here."))}</div>`);
			return;
		}
		this.data.days.forEach((day) => {
			const $day = $(`<div class="sp-fr-day mb-4">
				<div class="d-flex align-items-center mb-2">
					<h5 class="m-0 mr-2">${esc(frappe.datetime.str_to_user(day.work_date))}</h5>
					${
						day.reviewed
							? `<span class="indicator-pill green sp-fr-done">✓ ${esc(__("Reviewed"))}</span>`
							: ""
					}
				</div>
			</div>`).appendTo(this.$body);
			const waiting = day.vehicles.flatMap((v) =>
				// an entry flagged abnormal waits for its own decision, not the day's
				v.entries.filter((e) => !["Reviewed", "Flagged"].includes(e.status)).map((e) => e.name)
			);
			if (waiting.length) {
				this.button($day.find(".d-flex"), __("Mark day reviewed"), () =>
					frappe.confirm(__("Mark {0} entries reviewed?", [waiting.length]), () =>
						this.mark(waiting)
					)
				);
			}
			day.vehicles.forEach((group) => this.render_vehicle($day, day, group));
		});
	}

	render_vehicle($day, day, group) {
		const esc = frappe.utils.escape_html;
		const $group = $(`<div class="sp-fr-vehicle mb-3">
			<div class="d-flex align-items-center mb-1">
				<strong class="mr-2">${esc(group.vehicle)}</strong>
				${group.reviewed ? '<span class="text-success mr-2">✓</span>' : ""}
				${group.locked ? `<span class="indicator-pill gray mr-2">🔒 ${esc(__("Day locked"))}</span>` : ""}
			</div>
		</div>`).appendTo($day);
		if (group.locked) {
			const label = this.data.can_reopen ? __("Reopen Day") : __("Ask to Reopen");
			this.button($group.find(".d-flex"), label, () => this.reopen_dialog(group.vehicle, day.work_date));
		}
		const $table = $(`<table class="table table-sm table-hover sp-fr-table"><thead><tr>
			<th>${esc(__("Entry"))}</th><th>${esc(__("What"))}</th><th>${esc(__("Operator"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Flags"))}</th>
			<th>${esc(__("Status"))}</th><th></th>
		</tr></thead><tbody></tbody></table>`).appendTo($group);
		group.entries.forEach((row) => this.render_entry($table.find("tbody"), row));
	}

	render_entry($tbody, row) {
		const esc = frappe.utils.escape_html;
		const flags = row.flags
			.map(
				(f) =>
					`<span class="indicator-pill ${f.flag === "missing" ? "orange" : "red"} mr-1 mb-1" title="${esc(
						f.detail || ""
					)}">${esc(f.label)}</span><div class="small text-muted mb-1">${esc(f.detail || "")}</div>`
			)
			.join("");
		const colour = { Reviewed: "green", Flagged: "red", Locked: "gray" }[row.status] || "blue";
		const $tr = $(`<tr>
			<td><a href="/app/sp-field-entry/${encodeURIComponent(row.name)}">${esc(row.name)}</a>
				<div class="small text-muted">${esc(__(row.entry_kind))}${
			row.reopened ? ` · ${esc(__("Reopened"))}` : ""
		}</div></td>
			<td>${esc(row.what || "")}<div class="small text-muted">${esc(
			[row.who, row.place].filter(Boolean).join(" · ")
		)}</div>${row.note ? `<div class="small">${esc(row.note)}</div>` : ""}</td>
			<td>${esc(row.holder_name || "")}</td>
			<td class="text-right">${row.amount ? esc(format_currency(row.amount)) : ""}</td>
			<td>${flags}</td>
			<td><span class="indicator-pill ${colour}">${esc(__(row.status))}</span>${
			row.reviewed_by_name ? `<div class="small text-muted">${esc(row.reviewed_by_name)}</div>` : ""
		}</td>
			<td class="text-nowrap"></td>
		</tr>`).appendTo($tbody);
		const $actions = $tr.find("td:last");
		if (row.missing_fields.length) {
			this.button($actions, __("Complete"), () => this.complete_dialog(row));
		}
		if (row.status !== "Reviewed") {
			this.button($actions, __("Mark Reviewed"), () => this.mark([row.name]), "btn-primary");
		}
		if (row.status !== "Flagged") {
			this.button($actions, __("Abnormal"), () => this.abnormal_dialog(row), "btn-danger");
		}
	}

	button($cell, label, handler, style = "btn-default") {
		$(`<button class="btn btn-xs ${style} ml-1"></button>`).text(label).on("click", handler).appendTo($cell);
	}

	async mark(names) {
		const { message: done } = await frappe.call({
			method: `${SP_FR_API}.mark_reviewed`,
			args: { names },
			freeze: true,
		});
		frappe.show_alert({ message: __("{0} marked reviewed.", [done]), indicator: "green" });
		this.load();
	}

	ask(title, fields, label, method, args, message) {
		const dialog = new frappe.ui.Dialog({
			title,
			fields,
			primary_action_label: label,
			primary_action: async (values) => {
				await frappe.call({ method: `${SP_FR_API}.${method}`, args: args(values), freeze: true });
				dialog.hide();
				frappe.show_alert({ message, indicator: "green" });
				this.load();
			},
		});
		dialog.show();
	}

	complete_dialog(row) {
		const fields = row.missing_fields.map((fieldname) => ({ fieldname, ...SP_FR_FIELDS[fieldname] }));
		fields.push({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 });
		this.ask(
			__("Complete {0}", [row.name]),
			fields,
			__("Save"),
			"complete",
			({ reason, ...values }) => ({
				name: row.name,
				reason,
				values: Object.fromEntries(Object.entries(values).filter(([, v]) => v)),
			}),
			__("Saved.")
		);
	}

	abnormal_dialog(row) {
		this.ask(
			__("Flag {0} abnormal", [row.name]),
			[{ fieldname: "note", fieldtype: "Small Text", label: __("Note for the admin"), reqd: 1 }],
			__("Send to the admin"),
			"flag_abnormal",
			({ note }) => ({ name: row.name, note }),
			__("Sent to the admin.")
		);
	}

	reopen_dialog(vehicle, work_date) {
		this.ask(
			__("Reopen {0} on {1}", [vehicle, frappe.datetime.str_to_user(work_date)]),
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			this.data.can_reopen ? __("Reopen") : __("Ask to Reopen"),
			"reopen_day",
			({ reason }) => ({ vehicle, work_date, reason }),
			this.data.can_reopen ? __("Reopened.") : __("Sent for a decision")
		);
	}
}

$(`<style>
	.sp-fr-day h5 { font-weight: bold; }
	.sp-fr-done { font-weight: bold; }
	.sp-fr-table td { vertical-align: top; }
</style>`).appendTo(document.head);
