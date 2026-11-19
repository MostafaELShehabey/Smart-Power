// MR1 Site materials (SP-90): what a site holds, asks for, uses and sends back. No price reaches this
// page. The rules are on the server (smart_power.sp_stock.site_materials).
const SP_SITE_API = "smart_power.sp_stock.site_materials";

frappe.pages["sp-site-materials"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Site Materials"), single_column: true });
	wrapper.sp_site = new SPSiteMaterials(page);
};

frappe.pages["sp-site-materials"].on_page_show = function (wrapper) {
	wrapper.sp_site?.show();
};

class SPSiteMaterials {
	constructor(page) {
		this.page = page;
		this.station = page.add_field({
			fieldname: "station",
			fieldtype: "Select",
			label: __("Station"),
			change: () => this.refresh(),
		});
		page.set_primary_action(__("Request Materials"), () => this.request(), "add");
		this.$main = $('<div class="sp-site-materials"></div>').appendTo(page.main);
	}

	async show() {
		const { message: sites } = await frappe.call(`${SP_SITE_API}.my_sites`);
		const current = this.station.get_value();
		this.station.df.options = [
			{ value: "", label: __("Choose a station") },
			...sites.map((s) => ({ value: s.name, label: s.customer_name ? `${s.name} · ${s.customer_name}` : s.name })),
		];
		this.station.refresh();
		this.station.set_input(current || (sites.length === 1 ? sites[0].name : ""));
		this.refresh();
	}

	async refresh() {
		const esc = frappe.utils.escape_html;
		const station = this.station.get_value();
		this.$main.empty();
		if (!station) {
			$(`<p class="text-muted mt-3">${esc(__("Choose a station to see what its site holds."))}</p>`).appendTo(this.$main);
			return;
		}
		const { message } = await frappe.call(`${SP_SITE_API}.site_overview`, { station });
		this.data = message;
		this.render_stock(message);
		this.render_list(__("My Requests"), message.requests, "Material Request", (r) => r.transfer || "");
		this.render_list(__("My Returns"), message.returns, "Stock Entry", () => "");
	}

	render_stock(data) {
		const esc = frappe.utils.escape_html;
		const rows = data.stock
			.map(
				(l) => `<tr class="sp-site-stock"><td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)}</div></td>
					<td class="text-right text-nowrap">${esc(String(l.actual_qty))} ${esc(__(l.stock_uom || ""))}</td></tr>`
			)
			.join("");
		const $card = $(`<div class="frappe-card p-3 my-3">
			<div class="d-flex flex-wrap justify-content-between align-items-center mb-2" style="gap: 8px">
				<h6 class="mb-0">${esc(__("On Site"))} · ${esc(data.site)}</h6>
				<div class="d-flex flex-wrap" style="gap: 8px">
					${data.stock.length ? `<button class="btn btn-default btn-sm sp-site-return">${esc(__("Return Leftovers"))}</button>` : ""}
					${data.stock.length && data.can_consume ? `<button class="btn btn-primary btn-sm sp-site-consume">${esc(__("Record Consumption"))}</button>` : ""}
				</div>
			</div>
			${rows ? `<div class="table-responsive"><table class="table table-sm mb-0"><tbody>${rows}</tbody></table></div>` : `<p class="text-muted mb-0">${esc(__("Nothing is on this site."))}</p>`}
		</div>`).appendTo(this.$main);
		$card.find(".sp-site-consume").on("click", () => this.move("record_consumption", __("Record Consumption")));
		$card.find(".sp-site-return").on("click", () => this.move("return_leftovers", __("Return Leftovers")));
	}

	render_list(title, rows, doctype, extra) {
		const esc = frappe.utils.escape_html;
		if (!rows.length) return;
		const colors = { Open: "orange", Sent: "blue", Converted: "green", Received: "green", Discrepancy: "red" };
		const body = rows
			.map(
				(r) => `<tr><td><a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(r.name)}">${esc(r.name)}</a></td>
					<td><span class="indicator-pill ${colors[r.status] || "gray"}">${esc(__(r.status))}</span></td>
					<td class="small text-muted">${esc(extra(r))}</td></tr>`
			)
			.join("");
		$(`<div class="frappe-card p-3 mb-3"><h6 class="mb-2">${esc(title)}</h6>
			<div class="table-responsive"><table class="table table-sm mb-0"><tbody>${body}</tbody></table></div></div>`).appendTo(this.$main);
	}

	// consumption and returns: only what the site holds, with the serials of a serial-tracked item
	move(method, title) {
		const esc = frappe.utils.escape_html;
		const rows = this.data.stock
			.map(
				(l) => `<tr class="sp-site-line" data-item="${esc(l.item_code)}">
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(__("On site: {0}", [l.actual_qty]))}</div>
						${l.serial ? `<textarea class="form-control input-sm mt-1 sp-site-serial" rows="2" placeholder="${esc(__("One serial number on each line."))}"></textarea>` : ""}</td>
					<td style="max-width: 120px"><input type="number" min="0" max="${esc(String(l.actual_qty))}" class="form-control input-sm sp-site-qty" value="0"></td>
				</tr>`
			)
			.join("");
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{
					fieldname: "lines",
					fieldtype: "HTML",
					options: `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>${esc(__("Item"))}</th><th>${esc(__("Qty"))}</th></tr></thead><tbody>${rows}</tbody></table></div>`,
				},
			],
			primary_action_label: title,
			primary_action: async () => {
				const items = dialog.$wrapper
					.find(".sp-site-line")
					.map((_, el) => ({
						item_code: el.dataset.item,
						qty: flt($(el).find(".sp-site-qty").val()),
						serial_no: $(el).find(".sp-site-serial").val() || null,
					}))
					.get()
					.filter((row) => row.qty > 0);
				if (!items.length) {
					frappe.msgprint(__("Enter the quantity of at least one item."));
					return;
				}
				await frappe.call({
					method: `${SP_SITE_API}.${method}`,
					args: { values: { station: this.data.station, items } },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Saved"), indicator: "green" });
				this.refresh();
			},
		});
		dialog.show();
	}

	request() {
		const station = this.station.get_value();
		if (!station) {
			frappe.msgprint(__("Choose a station first."));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Request Materials"),
			size: "large",
			fields: [
				{ fieldname: "needed_by", fieldtype: "Date", label: __("Needed By"), reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Items"),
					reqd: 1,
					in_place_edit: true,
					data: [],
					fields: [
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), in_list_view: 1, reqd: 1, columns: 7 }, // sp-allow-number: grid column width
						{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, reqd: 1, columns: 3 }, // sp-allow-number: grid column width
					],
				},
			],
			primary_action_label: __("Send Request"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_SITE_API}.request_materials`,
					args: { values: { ...values, station } },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Request sent to purchasing"), indicator: "green" });
				this.refresh();
			},
		});
		dialog.show();
	}
}
