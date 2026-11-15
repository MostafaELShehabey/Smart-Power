// G4 Notifications (SP-40): my feed, unread first and grouped by day; opening an item marks it read
// and opens its record; Mark All Read. Per event, I choose whether it also pushes to my phone (the
// in-app feed is always on). The rules are on the server (smart_power.notify).

const SP_NT_API = "smart_power.notify";

frappe.pages["sp-notifications"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Notifications"), single_column: true });
	wrapper.sp_notifications = new SPNotifications(page);
};

frappe.pages["sp-notifications"].on_page_show = function (wrapper) {
	wrapper.sp_notifications && wrapper.sp_notifications.refresh();
};

class SPNotifications {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Mark All Read"), async () => {
			await frappe.call("frappe.desk.doctype.notification_log.notification_log.mark_all_as_read");
			this.refresh();
		});
		this.page.add_inner_button(__("Push Settings"), () => this.preferences());
		this.$body = $('<div class="sp-nt-body"></div>').appendTo(this.page.main);
		frappe.realtime.on("sp_counts", () => this.refresh());
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_NT_API}.feed`);
		this.data = message;
		this.render();
		// the sidebar bell keeps its own count: give it the server's after a read here
		const bell = frappe.app?.sidebar?.notifications?.tabs?.notifications;
		bell && bell.update_count_badge && bell.update_count_badge(message.unread);
	}

	render() {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		this.page.set_indicator(
			this.data.unread ? __("{0} unread", [this.data.unread]) : __("All read"),
			this.data.unread ? "blue" : "gray"
		);
		if (!this.data.items.length) {
			$(`<div class="text-muted text-center p-5">${esc(__("No notifications yet."))}</div>`).appendTo(this.$body);
			return;
		}
		const unread = this.data.items.filter((n) => !n.read);
		const read = this.data.items.filter((n) => n.read);
		const group = (rows) => {
			const days = {};
			rows.forEach((n) => {
				const day = n.creation.slice(0, 10); // sp-allow-number: the date part of a datetime
				(days[day] = days[day] || []).push(n);
			});
			return days;
		};
		[
			[__("Not read yet"), group(unread)],
			[__("Already read"), group(read)],
		].forEach(([title, days]) => {
			if (!Object.keys(days).length) return;
			const $section = $(`<div class="sp-nt-section"><h6>${esc(title)}</h6></div>`).appendTo(this.$body);
			Object.keys(days).forEach((day) => {
				$section.append(`<div class="sp-nt-day text-muted small">${esc(this.day_label(day))}</div>`);
				days[day].forEach((n) => this.item(n).appendTo($section));
			});
		});
	}

	day_label(day) {
		const today = frappe.datetime.get_today();
		if (day === today) return __("Today");
		if (day === frappe.datetime.add_days(today, -1)) return __("Yesterday");
		return frappe.datetime.str_to_user(day);
	}

	item(n) {
		const esc = frappe.utils.escape_html;
		const $item = $(`<div class="sp-nt-item ${n.read ? "" : "sp-nt-unread"}">
			<div class="sp-nt-subject"></div>
			<div class="text-muted small">${esc(n.event_label || "")}${n.event_label ? " · " : ""}${esc(
				frappe.datetime.prettyDate(n.creation)
			)}</div>
		</div>`);
		$item.find(".sp-nt-subject").text(frappe.utils.html2text(n.subject || ""));
		$item.on("click", async () => {
			if (!n.read) {
				await frappe.call("frappe.desk.doctype.notification_log.notification_log.mark_as_read", { docname: n.name });
			}
			if (n.document_type && n.document_name) {
				frappe.set_route("Form", n.document_type, n.document_name);
			} else {
				this.refresh();
			}
		});
		return $item;
	}

	async preferences() {
		const { message: rows } = await frappe.call(`${SP_NT_API}.preferences`);
		const esc = frappe.utils.escape_html;
		const d = new frappe.ui.Dialog({
			title: __("Push Settings"),
			fields: [{ fieldname: "list", fieldtype: "HTML" }],
		});
		const $list = $(`<div>
			<p class="text-muted small">${esc(__("Every event always appears here in the app. Tick the ones that should also push to your phone."))}</p>
		</div>`);
		rows.forEach((r, i) => {
			// the events of my roles first, then the rest
			if (i === 0 || r.mine !== rows[i - 1].mine) {
				$list.append(`<h6 class="mt-3">${esc(r.mine ? __("Your events") : __("Other events"))}</h6>`);
			}
			const $row = $(`<label class="sp-nt-pref ${r.mine ? "" : "text-muted"}">
				<input type="checkbox"> ${esc(r.label)}</label>`).appendTo($list);
			$row.find("input")
				.prop("checked", r.push)
				.on("change", async (e) => {
					await frappe.call(`${SP_NT_API}.set_push`, { event: r.event, push: e.target.checked ? 1 : 0 });
					frappe.show_alert({ message: __("Saved"), indicator: "green" });
				});
		});
		d.fields_dict.list.$wrapper.append($list);
		d.show();
	}
}

$(`<style>
	.sp-nt-body { max-width: 760px; padding: 0 16px; }
	.sp-nt-section { margin-bottom: 16px; }
	.sp-nt-day { margin: 10px 0 4px; }
	.sp-nt-item { padding: 8px 12px; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); margin-bottom: 6px; cursor: pointer; background: var(--card-bg); }
	.sp-nt-item:hover { background: var(--fg-hover-color); }
	.sp-nt-unread { border-inline-start: 3px solid var(--blue-500); }
	.sp-nt-unread .sp-nt-subject { font-weight: var(--weight-semibold); }
	.sp-nt-pref { display: block; font-weight: normal; margin-bottom: 4px; }
</style>`).appendTo(document.head);
