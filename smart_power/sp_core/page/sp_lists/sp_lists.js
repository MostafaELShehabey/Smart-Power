// X4 Lists (SP-32): the admin edits the drop-down lists without a developer.
// One tab per list; add, rename, deactivate and drag to reorder. The rules live on the server
// (smart_power.sp_core.services.lists and the SP List Value controller).

const SP_LISTS_API = "smart_power.sp_core.services.lists";
const SP_LIST_DOCTYPE = "SP List Value";

frappe.pages["sp-lists"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Lists"),
		single_column: false,
	});
	// The list names come from SP List Value's meta, which the desk loads on demand.
	frappe.model.with_doctype(SP_LIST_DOCTYPE, () => {
		wrapper.sp_lists = new SPLists(page);
	});
};

frappe.pages["sp-lists"].on_page_show = function (wrapper) {
	wrapper.sp_lists && wrapper.sp_lists.refresh();
};

class SPLists {
	constructor(page) {
		this.page = page;
		this.list_names = frappe.meta
			.get_docfield(SP_LIST_DOCTYPE, "list_name")
			.options.split("\n")
			.filter(Boolean);
		this.current = frappe.utils.get_query_params().list || this.list_names[0];
		this.page.set_primary_action(__("Add Value"), () => this.add_value(), "add");
		this.page.add_inner_button(__("Open as List"), () =>
			frappe.set_route("List", SP_LIST_DOCTYPE, { list_name: this.current })
		);
		this.make_sidebar();
		this.$body = $('<div class="sp-lists-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	make_sidebar() {
		const $ul = $('<ul class="list-unstyled sidebar-menu sp-lists-menu"></ul>').appendTo(
			this.page.sidebar
		);
		this.list_names.forEach((name) => {
			$(`<li class="sidebar-item"><a href="#"></a></li>`)
				.attr("data-list", name)
				.find("a")
				.text(__(name))
				.on("click", (e) => {
					e.preventDefault();
					this.current = name;
					// keep the tab in the address so a reload or a shared link opens the same list
					window.history.replaceState(null, "", `?list=${encodeURIComponent(name)}`);
					this.refresh();
				})
				.end()
				.appendTo($ul);
		});
		this.$menu = $ul;
	}

	async refresh() {
		this.page.set_title(__("Lists") + ": " + __(this.current));
		this.$menu.find("li").removeClass("selected");
		this.$menu.find(`li[data-list="${this.current}"]`).addClass("selected");
		frappe.dom.freeze();
		try {
			const { message } = await frappe.call(`${SP_LISTS_API}.get_list`, {
				list_name: this.current,
			});
			this.render(message || []);
		} finally {
			frappe.dom.unfreeze();
		}
	}

	render(values) {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		if (!values.length) {
			this.$body.append(
				`<div class="text-muted p-4">${esc(
					__("This list has no values yet. Use Add Value.")
				)}</div>`
			);
			return;
		}
		const $table = $(`<table class="table table-hover sp-lists-table">
			<thead><tr>
				<th></th>
				<th>${esc(__("Value (Arabic)"))}</th>
				<th>${esc(__("Value (English)"))}</th>
				<th>${esc(__("Code"))}</th>
				<th>${esc(__("Active"))}</th>
				<th></th>
			</tr></thead>
			<tbody></tbody>
		</table>`).appendTo(this.$body);
		const $tbody = $table.find("tbody");
		values.forEach((v) => {
			const $row = $(`<tr>
				<td class="sp-drag text-muted" title="${esc(__("Drag to reorder"))}">⋮⋮</td>
				<td>${esc(v.value_ar)}</td>
				<td>${esc(v.value_en || "")}</td>
				<td><code>${esc(v.code)}</code></td>
				<td><input type="checkbox" class="sp-active"></td>
				<td class="text-right">
					<button class="btn btn-xs btn-default sp-rename">${esc(__("Rename"))}</button>
				</td>
			</tr>`).attr("data-name", v.name);
			$row.toggleClass("text-muted", !v.is_active);
			$row.find(".sp-active")
				.prop("checked", !!v.is_active)
				.on("change", (e) => this.set_active(v.name, e.target.checked));
			$row.find(".sp-rename").on("click", () => this.rename(v));
			$tbody.append($row);
		});
		Sortable.create($tbody.get(0), {
			handle: ".sp-drag",
			onEnd: () => this.save_order($tbody),
		});
	}

	async save_order($tbody) {
		const names = $tbody
			.find("tr")
			.map((_i, tr) => $(tr).attr("data-name"))
			.get();
		await frappe.call(`${SP_LISTS_API}.reorder`, { list_name: this.current, names });
		frappe.show_alert({ message: __("Order saved"), indicator: "green" });
	}

	async set_active(name, active) {
		await frappe.call(`${SP_LISTS_API}.set_active`, { name, active: active ? 1 : 0 });
		this.refresh();
	}

	add_value() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Value to {0}", [__(this.current)]),
			fields: [
				{ fieldname: "value_ar", fieldtype: "Data", label: __("Value (Arabic)"), reqd: 1 },
				{ fieldname: "value_en", fieldtype: "Data", label: __("Value (English)") },
				{
					fieldname: "code",
					fieldtype: "Data",
					label: __("Code"),
					reqd: 1,
					description: __("Short key used by reports and code, e.g. PUMP."),
				},
				{
					fieldname: "parent_value",
					fieldtype: "Link",
					label: __("Parent Value"),
					options: SP_LIST_DOCTYPE,
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				await frappe.db.insert({
					doctype: SP_LIST_DOCTYPE,
					list_name: this.current,
					is_active: 1,
					...values,
				});
				dialog.hide();
				this.refresh();
			},
		});
		dialog.show();
	}

	rename(v) {
		const dialog = new frappe.ui.Dialog({
			title: __("Rename"),
			fields: [
				{
					fieldname: "value_ar",
					fieldtype: "Data",
					label: __("Value (Arabic)"),
					reqd: 1,
					default: v.value_ar,
				},
				{
					fieldname: "value_en",
					fieldtype: "Data",
					label: __("Value (English)"),
					default: v.value_en,
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.db.set_value(SP_LIST_DOCTYPE, v.name, values);
				dialog.hide();
				this.refresh();
			},
		});
		dialog.show();
	}
}
