// G3 Task inbox (SP-39): everything waiting for me, by type; open the record, approve or reject
// right here where the type allows it, snooze until a date and time. The rules are on the server
// (smart_power.sp_core.inbox); the list follows every change at once (realtime sp_tasks).

const SP_TI_API = "smart_power.sp_core.inbox";

frappe.pages["sp-task-inbox"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("My Tasks"), single_column: true });
	wrapper.sp_task_inbox = new SPTaskInbox(page);
};

frappe.pages["sp-task-inbox"].on_page_show = function (wrapper) {
	wrapper.sp_task_inbox && wrapper.sp_task_inbox.refresh();
};

class SPTaskInbox {
	constructor(page) {
		this.page = page;
		this.type = null;
		this.snoozed = false;
		this.$chips = $('<div class="sp-ti-chips d-flex flex-wrap gap-2 mb-3"></div>').appendTo(this.page.main);
		this.$list = $('<div class="sp-ti-list"></div>').appendTo(this.page.main);
		this.snooze_btn = this.page.add_inner_button(__("Snoozed"), () => {
			this.snoozed = !this.snoozed;
			this.type = null;
			this.refresh();
		});
		frappe.realtime.on("sp_tasks", () => this.refresh());
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_TI_API}.my_tasks`, {
			task_type: this.type,
			snoozed: this.snoozed ? 1 : 0,
		});
		this.data = message;
		this.render();
	}

	render() {
		const esc = frappe.utils.escape_html;
		const total = Object.values(this.data.counts).reduce((a, b) => a + b, 0);
		this.page.set_title(this.snoozed ? __("Snoozed Tasks") : __("My Tasks"));
		this.page.set_indicator(
			this.snoozed ? __("{0} snoozed", [total]) : __("{0} waiting", [total]),
			total ? "orange" : "green"
		);
		this.snooze_btn.text(this.snoozed ? __("Back to Waiting") : `${__("Snoozed")} (${this.data.snoozed})`);

		// type chips: All, then each type that has tasks
		this.$chips.empty();
		const chip = (label, count, type) =>
			$(`<button class="btn btn-xs ${this.type === type ? "btn-primary" : "btn-default"}">
				${esc(label)} <span class="badge">${count}</span></button>`)
				.on("click", () => {
					this.type = type;
					this.refresh();
				})
				.appendTo(this.$chips);
		chip(__("All"), total, null);
		Object.entries(this.data.counts).forEach(([type, count]) => chip(__(type), count, type));

		this.$list.empty();
		if (!this.data.tasks.length) {
			$(`<div class="text-muted text-center p-5">${esc(
				this.snoozed ? __("Nothing snoozed.") : __("Nothing waiting for you.")
			)}</div>`).appendTo(this.$list);
			return;
		}
		this.data.tasks.forEach((t) => this.row(t).appendTo(this.$list));
	}

	row(t) {
		const esc = frappe.utils.escape_html;
		const high = t.priority === "High";
		const thumb = t.image
			? `<a href="${esc(t.image)}" target="_blank" rel="noopener"><img src="${esc(t.image)}"
				style="width: 56px; height: 56px; object-fit: cover; border-radius: 6px;"></a>`
			: "";
		const amount = t.amount ? `<b>${esc(format_currency(t.amount))}</b>` : "";
		const due = t.due_at ? `${__("Due")}: ${esc(frappe.datetime.str_to_user(t.due_at))}` : "";
		const snoozed = t.snoozed_until
			? `${__("Until")}: ${esc(frappe.datetime.str_to_user(t.snoozed_until))}`
			: "";
		const $row = $(`<div class="frappe-card p-3 mb-2 d-flex align-items-center gap-3 ${high ? "border-danger" : ""}">
			${thumb}
			<div class="flex-grow-1">
				<div>${high ? `<span class="indicator-pill red">${esc(__("High"))}</span> ` : ""}<b>${esc(t.subject)}</b></div>
				<div class="text-muted small">
					<span class="indicator-pill gray">${esc(__(t.task_type))}</span>
					${esc(frappe.datetime.prettyDate(t.creation))} ${amount ? "· " + amount : ""} ${due ? "· " + due : ""} ${snoozed ? "· " + snoozed : ""}
				</div>
			</div>
			<div class="sp-ti-actions d-flex gap-2 flex-wrap"></div>
		</div>`);
		const $actions = $row.find(".sp-ti-actions");
		const button = (label, cls, fn) =>
			$(`<button class="btn btn-xs ${cls}">${esc(label)}</button>`).on("click", fn).appendTo($actions);
		if (t.reference_doctype && t.reference_name) {
			button(__("Open"), "btn-default", () => frappe.set_route("Form", t.reference_doctype, t.reference_name));
		}
		if (this.snoozed) {
			button(__("Wake Now"), "btn-default", () => this.call("wake", { task: t.name }));
			return $row;
		}
		if (t.inline) {
			button(__("Approve"), "btn-primary", () =>
				frappe.confirm(__("Approve: {0}?", [esc(t.subject)]), () =>
					this.call("act", { task: t.name, action: "approve" }, __("Approved"))
				)
			);
			button(__("Reject"), "btn-danger", () =>
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
					(v) => this.call("act", { task: t.name, action: "reject", reason: v.reason }, __("Rejected")),
					__("Reject"),
					__("Reject")
				)
			);
		}
		button(__("Snooze"), "btn-default", () => this.snooze(t));
		return $row;
	}

	snooze(t) {
		// tomorrow morning by default: the start of the working day
		const tomorrow = frappe.datetime.add_days(frappe.datetime.get_today(), 1) + " 09:00:00"; // sp-allow-number: 9 am
		const dialog = new frappe.ui.Dialog({
			title: __("Snooze until"),
			fields: [{ fieldname: "until", fieldtype: "Datetime", label: __("Until"), reqd: 1, default: tomorrow }],
			primary_action_label: __("Snooze"),
			primary_action: (v) => {
				dialog.hide();
				this.call("snooze", { task: t.name, until: v.until }, __("Snoozed"));
			},
		});
		dialog.show();
	}

	async call(method, args, done) {
		await frappe.xcall(`${SP_TI_API}.${method}`, args);
		done && frappe.show_alert({ message: done, indicator: "green" });
		this.refresh();
		$(document).trigger("sp_tasks_changed"); // the shell's count, without waiting for realtime
	}
}
