// G6 Profile (SP-42): my roles (read-only), language, notification channels, my custody and the
// cash I hold (days held; red past the limit), change password. Only ever my own accounts. The
// rules are on the server (smart_power.sp_core.profile).

const SP_PF_API = "smart_power.sp_core.profile";

frappe.pages["sp-profile"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("My Profile"), single_column: true });
	wrapper.sp_profile = new SPProfile(page);
};

frappe.pages["sp-profile"].on_page_show = function (wrapper) {
	wrapper.sp_profile && wrapper.sp_profile.refresh();
};

class SPProfile {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Change Password"), () => this.change_password());
		this.$body = $('<div class="sp-pf-body"></div>').appendTo(this.page.main);
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_PF_API}.profile`);
		this.data = message;
		this.render();
	}

	render() {
		const esc = frappe.utils.escape_html;
		const d = this.data;
		this.$body.empty();
		const section = (title) =>
			$(`<div class="sp-pf-section"><h6 class="sp-pf-title">${esc(title)}</h6></div>`).appendTo(this.$body);

		// who I am and my roles
		const $me = section(__("Account"));
		$me.append(`<div class="sp-pf-name">${esc(d.full_name || d.user)}</div>
			<div class="text-muted small">${esc(d.email || "")}${d.mobile ? " · " + esc(d.mobile) : ""}</div>
			<div class="sp-pf-roles mt-2">${
				d.roles.map((r) => `<span class="indicator-pill gray">${esc(r.label)}</span>`).join(" ") ||
				`<span class="text-muted small">${esc(__("No roles"))}</span>`
			}</div>
			<div class="text-muted small mt-1">${esc(__("Roles are set by the admin."))}</div>`);

		// my money
		const $money = section(__("My custody and cash held"));
		if (!d.money.length) {
			$money.append(`<div class="text-muted small">${esc(__("You hold no company money."))}</div>`);
		}
		d.money.forEach((m) => {
			const days = m.days_held ? __("{0} days", [m.days_held]) : "";
			$money.append(`<div class="sp-pf-money ${m.over ? "sp-pf-over" : ""}">
				<div>
					<div>${esc(m.account_name)}</div>
					<div class="text-muted small">${esc(m.kind === "Custody" ? __("Custody") : __("Cash held"))}</div>
				</div>
				<div class="text-right">
					<div class="sp-pf-amount">${esc(format_currency(m.balance))}</div>
					${days ? `<div class="small ${m.over ? "text-danger" : "text-muted"}">${esc(days)}${
						m.limit ? " / " + esc(__("limit {0}", [m.limit])) : ""
					}</div>` : ""}
				</div>
			</div>`);
		});
		if (d.money.some((m) => m.kind === "Custody")) {
			$(`<button class="btn btn-xs btn-default mt-2"></button>`)
				.text(__("My Custody"))
				.on("click", () => frappe.set_route("sp-my-custody"))
				.appendTo($money);
		}

		// language
		const $lang = section(__("Language"));
		const $select = $(`<select class="form-control input-sm sp-pf-lang">
			<option value="ar">العربية</option><option value="en">English</option></select>`)
			.val(d.language === "en" ? "en" : "ar")
			.appendTo($lang);
		$select.on("change", async () => {
			await frappe.call({ method: `${SP_PF_API}.set_language`, args: { language: $select.val() }, freeze: true });
			frappe.ui.toolbar.clear_cache(); // the Desk reloads in the new language and direction
		});

		// notification channels
		const $note = section(__("Notifications"));
		[
			["in_app", __("In the app")],
			["email", __("By email")],
		].forEach(([key, label]) => {
			const $row = $(`<label class="sp-pf-check"><input type="checkbox"> ${esc(label)}</label>`).appendTo($note);
			$row.find("input")
				.prop("checked", d.channels[key])
				.on("change", async (e) => {
					const { message } = await frappe.call(`${SP_PF_API}.set_channels`, {
						channels: { [key]: e.target.checked },
					});
					d.channels = message;
					frappe.show_alert({ message: __("Saved"), indicator: "green" });
				});
		});
	}

	change_password() {
		const d = new frappe.ui.Dialog({
			title: __("Change Password"),
			fields: [
				{ fieldname: "old_password", fieldtype: "Password", label: __("Current Password"), reqd: 1 },
				{ fieldname: "new_password", fieldtype: "Password", label: __("New Password"), reqd: 1 },
				{ fieldname: "confirm_password", fieldtype: "Password", label: __("Confirm New Password"), reqd: 1 },
			],
			primary_action_label: __("Change Password"),
			primary_action: async (values) => {
				if (values.new_password !== values.confirm_password) {
					frappe.msgprint(__("The new passwords do not match."));
					return;
				}
				await frappe.call({
					method: "frappe.core.doctype.user.user.update_password",
					args: { old_password: values.old_password, new_password: values.new_password },
					freeze: true,
				});
				d.hide();
				frappe.show_alert({ message: __("Password changed"), indicator: "green" });
			},
		});
		d.show();
	}
}

$(`<style>
	.sp-pf-body { max-width: 720px; }
	.sp-pf-section { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 12px 16px; margin-bottom: 12px; background: var(--card-bg); }
	.sp-pf-title { margin-bottom: 8px; }
	.sp-pf-name { font-size: var(--text-lg); font-weight: var(--weight-semibold); }
	.sp-pf-roles .indicator-pill { margin: 0 0 4px; }
	.sp-pf-money { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border-color); }
	.sp-pf-money:last-of-type { border-bottom: 0; }
	.sp-pf-over .sp-pf-amount { color: var(--red-600); }
	.sp-pf-amount { font-weight: var(--weight-semibold); }
	.sp-pf-lang { max-width: 200px; }
	.sp-pf-check { display: block; font-weight: normal; }
</style>`).appendTo(document.head);
