// X1 Users and roles (SP-130): the team's logins in one screen. Add a user (a one-time temporary
// password to pass on), disable, give or take role keys, reset the password, unlock, choose the
// home and entry mode, make the money accounts, revoke the phone. The rules are on the server
// (smart_power.sp_core.users_roles); every change is in the audit log (X13).
const SP_UR_COLUMNS = 2; // sp-allow-number: role keys shown in two columns
const SP_UR_API = "smart_power.sp_core.users_roles";

frappe.pages["sp-users-roles"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Users and Roles"), single_column: true });
	frappe.pages["sp-users-roles"].sp_users_roles = new SPUsersRoles(page);
};

class SPUsersRoles {
	constructor(page) {
		this.page = page;
		page.set_primary_action(__("Add User"), () => this.add());
		this.search = page.add_field({
			fieldname: "search",
			fieldtype: "Data",
			label: __("Search"),
			change: () => this.render(),
		});
		this.$body = $('<div class="sp-ur-body"></div>').appendTo(page.main);
		this.refresh();
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_UR_API}.overview`);
		this.data = message;
		this.render();
	}

	label_of(key) {
		const k = this.data.keys.find((r) => r.key === key);
		return k ? k.label : key;
	}

	render() {
		const esc = frappe.utils.escape_html;
		const q = (this.search.get_value() || "").toLowerCase();
		const homes = Object.fromEntries(this.data.homes.map((h) => [h.value, h.label]));
		const rows = this.data.users
			.filter((u) => !q || `${u.full_name} ${u.name}`.toLowerCase().includes(q))
			.map((u, i) => {
				const status = !u.enabled
					? `<span class="indicator-pill gray">${esc(__("Disabled"))}</span>`
					: u.sp_login_locked
						? `<span class="indicator-pill red">${esc(__("Locked"))}</span>`
						: `<span class="indicator-pill green">${esc(__("Active"))}</span>`;
				const device = u.device
					? `${esc(u.device.device_name || u.device.device_id)}<div class="small text-muted">${esc(
							u.device.last_sync ? frappe.datetime.str_to_user(u.device.last_sync) : ""
						)}</div>`
					: `<span class="text-muted">—</span>`;
				return `<tr data-i="${i}"><td><b>${esc(u.full_name || u.name)}</b><div class="small text-muted">${esc(u.name)}</div></td>
					<td class="small">${u.keys.map((k) => esc(this.label_of(k))).join("، ")}</td>
					<td class="small">${esc(u.last_login ? frappe.datetime.str_to_user(u.last_login) : "")}</td>
					<td class="small">${device}</td><td class="small">${esc(__(u.sp_entry_mode || "Full"))}</td>
					<td class="small">${esc(homes[u.sp_home_page] || "")}</td><td>${status}</td>
					<td><button class="btn btn-xs btn-default sp-ur-act" data-user="${esc(u.name)}">${esc(__("Actions"))}</button></td></tr>`;
			})
			.join("");
		this.$body.html(`<table class="table table-sm"><thead><tr><th>${esc(__("User"))}</th><th>${esc(__("Roles"))}</th>
			<th>${esc(__("Last Login"))}</th><th>${esc(__("Mobile Device"))}</th><th>${esc(__("Entry Mode"))}</th>
			<th>${esc(__("Home"))}</th><th>${esc(__("Status"))}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`);
		this.$body.find(".sp-ur-act").on("click", (e) => this.actions(this.data.users.find((u) => u.name === e.currentTarget.dataset.user)));
	}

	key_options() {
		return this.data.keys.map((k) => ({ label: `${k.label} (${k.role})`, value: k.key }));
	}

	home_options() {
		return [{ label: "", value: "" }].concat(this.data.homes);
	}

	async call(method, args, message) {
		const r = await frappe.call({ method: `${SP_UR_API}.${method}`, args, freeze: true });
		if (message) frappe.show_alert({ message, indicator: "green" });
		this.refresh();
		return r.message;
	}

	show_password(user, password) {
		frappe.msgprint({
			title: __("Temporary password"),
			indicator: "orange",
			message: `${frappe.utils.escape_html(__("Give {0} this password; they change it at the first sign-in. It is shown only once.", [user]))}
				<div class="mt-3 mb-1 h4 text-center"><code>${frappe.utils.escape_html(password)}</code></div>`,
		});
	}

	add() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add User"),
			fields: [
				{ fieldname: "full_name", fieldtype: "Data", label: __("Full Name"), reqd: 1 },
				{ fieldname: "email", fieldtype: "Data", options: "Email", label: __("Email"), reqd: 1 },
				{ fieldname: "mobile_no", fieldtype: "Data", label: __("Mobile") },
				{ fieldname: "col", fieldtype: "Column Break" },
				{ fieldname: "entry_mode", fieldtype: "Select", label: __("Entry Mode"), options: ["Full", "Light"], default: "Full" },
				{ fieldname: "home", fieldtype: "Select", label: __("Home"), options: this.home_options() },
				{ fieldname: "sec", fieldtype: "Section Break", label: __("Roles") },
				{ fieldname: "keys", fieldtype: "MultiCheck", options: this.key_options(), columns: SP_UR_COLUMNS },
			],
			primary_action_label: __("Add"),
			primary_action: async (v) => {
				const r = await this.call("add_user", { values: { ...v, keys: dialog.fields_dict.keys.get_checked_options() } });
				dialog.hide();
				this.show_password(r.user, r.password);
			},
		});
		dialog.show();
	}

	actions(u) {
		const dialog = new frappe.ui.Dialog({
			title: u.full_name || u.name,
			fields: [
				{ fieldname: "keys", fieldtype: "MultiCheck", label: __("Roles"), options: this.key_options().map((o) => ({ ...o, checked: u.keys.includes(o.value) })), columns: SP_UR_COLUMNS },
				{ fieldname: "sec", fieldtype: "Section Break" },
				{ fieldname: "entry_mode", fieldtype: "Select", label: __("Entry Mode"), options: ["Full", "Light"], default: u.sp_entry_mode || "Full" },
				{ fieldname: "col", fieldtype: "Column Break" },
				{ fieldname: "home", fieldtype: "Select", label: __("Home"), options: this.home_options(), default: u.sp_home_page || "" },
			],
			primary_action_label: __("Save"),
			primary_action: async (v) => {
				await frappe.call({ method: `${SP_UR_API}.set_roles`, args: { user: u.name, keys: dialog.fields_dict.keys.get_checked_options() } });
				if ((v.entry_mode || "Full") !== (u.sp_entry_mode || "Full")) await frappe.call({ method: `${SP_UR_API}.set_entry_mode`, args: { user: u.name, mode: v.entry_mode } });
				if ((v.home || "") !== (u.sp_home_page || "")) await frappe.call({ method: `${SP_UR_API}.set_home`, args: { user: u.name, home: v.home || null } });
				dialog.hide();
				frappe.show_alert({ message: __("Saved"), indicator: "green" });
				this.refresh();
			},
		});
		const add = (label, fn) => dialog.add_custom_action(label, fn);
		add(__("Reset Password"), () =>
			frappe.confirm(__("Give {0} a new temporary password?", [u.full_name || u.name]), async () => {
				const password = await this.call("reset_password", { user: u.name });
				dialog.hide();
				this.show_password(u.name, password);
			})
		);
		if (u.sp_login_locked) add(__("Unlock"), async () => (await this.call("unlock", { user: u.name }, __("Unlocked")), dialog.hide()));
		add(u.enabled ? __("Disable") : __("Enable"), () =>
			frappe.confirm(u.enabled ? __("Disable {0}? They can no longer sign in.", [u.full_name || u.name]) : __("Enable {0}?", [u.full_name || u.name]), async () => {
				await this.call("set_enabled", { user: u.name, enabled: u.enabled ? 0 : 1 });
				dialog.hide();
			})
		);
		if (!u.accounts.transit || !u.accounts.custody) {
			add(__("Make Money Accounts"), async () => {
				await this.call("create_accounts", { user: u.name, transit: u.accounts.transit ? 0 : 1, custody: u.accounts.custody ? 0 : 1 }, __("Accounts made"));
				dialog.hide();
			});
		}
		if (u.device) {
			add(__("Revoke Device"), () =>
				frappe.confirm(__("Revoke {0}'s phone? It must sign in again.", [u.full_name || u.name]), async () => {
					await this.call("revoke_device", { device: u.device.name }, __("Device revoked"));
					dialog.hide();
				})
			);
		}
		dialog.show();
	}
}
