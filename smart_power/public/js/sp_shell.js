// App shell (SP-37): "+ New" and My Tasks in the dock, beside Frappe's search and bell.
// "+ New" lists only what this user may start (smart_power.shell.get_new_menu); My Tasks shows how
// many tasks wait now and follows every change at once (realtime sp_tasks, from the task inbox).
frappe.provide("smart_power.shell");

smart_power.shell = {
	API: "smart_power.shell",
	INBOX: "/desk/smart-power/sp-task-inbox",

	init() {
		const $utilities = $(".dock-utilities");
		if (!$utilities.length || $utilities.find(".sp-dock-new").length) return;
		const icon = (name) => `<span class="dock-item-icon">${frappe.utils.icon(name, "sm")}</span>`;
		this.$new = $(`<button class="dock-item sp-dock-new" aria-label="${__("New")}" title="${__("New")}">
			${icon("add")}</button>`).on("click", (e) => this.toggle_menu(e));
		this.$tasks = $(`<button class="dock-item sp-dock-tasks" aria-label="${__("My Tasks")}" title="${__("My Tasks")}">
			${icon("check")}<span class="sp-dock-count hidden" aria-live="polite"></span></button>`).on("click", () =>
			frappe.set_route(this.INBOX)
		);
		$utilities.append(this.$new, this.$tasks);
		this.refresh_counts();
		frappe.realtime.on("sp_tasks", () => this.refresh_counts());
		// an action in the inbox on this page (realtime covers the other tabs and other users' changes)
		$(document).on("sp_tasks_changed", () => this.refresh_counts());
	},

	async refresh_counts() {
		const { message } = await frappe.call({ method: `${this.API}.get_counts`, type: "GET" });
		const tasks = (message && message.tasks) || 0;
		this.$tasks
			.find(".sp-dock-count")
			.text(tasks > 99 ? "99+" : tasks) // sp-allow-number: the badge's widest number
			.toggleClass("hidden", !tasks);
	},

	async toggle_menu(e) {
		e.stopPropagation();
		if (this.$menu) return this.close_menu();
		const { message: actions } = await frappe.call(`${this.API}.get_new_menu`);
		const esc = frappe.utils.escape_html;
		this.$menu = $(`<div class="sp-new-menu dropdown-menu show" role="menu"></div>`).appendTo("body");
		if (!actions.length) {
			$(`<span class="dropdown-item text-muted">${esc(__("Nothing to start here."))}</span>`).appendTo(this.$menu);
		}
		actions.forEach((a) =>
			$(`<a class="dropdown-item" role="menuitem" href="#">${esc(a.label)}</a>`)
				.on("click", (ev) => {
					ev.preventDefault();
					this.close_menu();
					this.start(a);
				})
				.appendTo(this.$menu)
		);
		const rect = this.$new[0].getBoundingClientRect();
		const rtl = frappe.utils.is_rtl();
		this.$menu.css({
			position: "fixed",
			top: rect.top,
			[rtl ? "right" : "left"]: rtl ? window.innerWidth - rect.left + 8 : rect.right + 8, // sp-allow-number: gap px
		});
		$(document).one("click", () => this.close_menu());
	},

	close_menu() {
		this.$menu && this.$menu.remove();
		this.$menu = null;
	},

	start(action) {
		if (action.kind === "page") return frappe.set_route(action.target);
		if (action.kind === "new") return frappe.new_doc(action.target);
		if (action.target === "transfer") return smart_power.transfer_dialog({});
		if (action.target === "payment") {
			// a payment is recorded on a station: pick it first
			const d = new frappe.ui.Dialog({
				title: __("Payment on a Station"),
				fields: [{ fieldname: "station", fieldtype: "Link", options: "SP Station", label: __("Station"), reqd: 1 }],
				primary_action_label: __("Next"),
				primary_action: (v) => {
					d.hide();
					smart_power.record_payment_dialog({ station: v.station });
				},
			});
			d.show();
		}
	},
};

$(document).on("app_ready", () => smart_power.shell.init());
$(document).on("page-change", () => smart_power.shell.init());
