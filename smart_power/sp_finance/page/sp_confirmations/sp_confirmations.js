// A1 Confirmations (SP-115): every money item waiting for the admin, with its receipt and the
// entry it will post. Confirm, reject with a reason, or check a statement and bulk-confirm the
// selected items. The rules are on the server (smart_power.sp_finance.confirmations).

const SP_CF_API = "smart_power.sp_finance.confirmations";
const SP_CF_POLL_MS = 1500; // sp-allow-number: how often the bulk result is read

frappe.pages["sp-confirmations"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Confirmations"), single_column: true });
	wrapper.sp_confirmations = new SPConfirmations(page);
};

frappe.pages["sp-confirmations"].on_page_show = function (wrapper) {
	const page = wrapper.sp_confirmations;
	if (!page) return;
	// A14 (SP-126) opens the page on one month's dates
	const options = frappe.route_options || {};
	frappe.route_options = null;
	for (const key of ["from_date", "to_date"]) {
		if (options[key] && page.filters[key]) page.filters[key].set_value(options[key]);
	}
	page.refresh();
};

class SPConfirmations {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.page.add_inner_button(__("Confirm selected"), () => this.bulk());
		const change = () => this.refresh();
		this.filters = {
			account: this.page.add_field({
				fieldname: "account",
				fieldtype: "Link",
				options: "Account",
				label: __("Receiving Account"),
				get_query: () => ({ filters: { sp_account_kind: ["in", ["Official", "Transit"]], is_group: 0 } }),
				change,
			}),
			from_date: this.page.add_field({ fieldname: "from_date", fieldtype: "Date", label: __("From"), change }),
			to_date: this.page.add_field({ fieldname: "to_date", fieldtype: "Date", label: __("To"), change }),
		};
		this.$summary = $('<div class="sp-cf-summary mb-3 text-muted"></div>').appendTo(this.page.main);
		this.$body = $('<div class="sp-cf-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	values() {
		const out = {};
		Object.entries(this.filters).forEach(([k, f]) => {
			if (f.get_value()) out[k] = f.get_value();
		});
		return out;
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_CF_API}.pending`, { filters: this.values() });
		this.data = message;
		this.render();
	}

	render() {
		const esc = frappe.utils.escape_html;
		this.$summary.text(
			__("{0} waiting · {1}", [this.data.count, format_currency(this.data.amount)])
		);
		this.$body.empty();
		if (!this.data.items.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("Nothing waiting for confirmation."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-hover table-sm"><thead><tr>
			<th><input type="checkbox" class="sp-cf-all"></th><th>${esc(__("Type"))}</th>
			<th>${esc(__("Recorded By"))}</th><th>${esc(__("Date"))}</th><th>${esc(__("Account"))}</th>
			<th>${esc(__("Station"))}</th><th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Receipt"))}</th><th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		this.data.items.forEach((item) => {
			const photo = item.photo
				? `<a href="${esc(item.photo)}" target="_blank"><img src="${esc(item.photo)}" class="sp-cf-thumb"></a>`
				: "";
			const $tr = $(`<tr>
				<td><input type="checkbox" class="sp-cf-check" data-doctype="${esc(item.doctype)}" data-name="${esc(item.name)}"></td>
				<td><a href="/app/${frappe.router.slug(item.doctype)}/${encodeURIComponent(item.name)}">${esc(item.kind)}</a>
					<div class="small text-muted">${esc(item.party || "")}</div></td>
				<td>${esc(item.recorder_name || "")}</td>
				<td>${esc(frappe.datetime.str_to_user(item.date))}</td>
				<td>${esc(item.account || "")}</td>
				<td>${esc(item.station || "")}</td>
				<td class="text-right">${esc(format_currency(item.amount))}</td>
				<td>${photo}</td>
				<td class="text-nowrap"></td>
			</tr>`).appendTo($table.find("tbody"));
			const $act = $tr.find("td:last");
			const btn = (label, style, handler) =>
				$(`<button class="btn btn-xs ${style} mr-1"></button>`).text(label).on("click", handler).appendTo($act);
			btn(__("Preview"), "btn-default", () => this.preview(item));
			btn(__("Confirm"), "btn-primary", () => this.confirm(item));
			btn(__("Reject"), "btn-default", () => this.reject(item));
		});
		$table.find(".sp-cf-all").on("change", (e) => $table.find(".sp-cf-check").prop("checked", e.target.checked));
	}

	async preview(item) {
		const { message: lines } = await frappe.call(`${SP_CF_API}.preview`, { doctype: item.doctype, name: item.name });
		const esc = frappe.utils.escape_html;
		const rows = lines
			.map(
				(l) => `<tr><td>${esc(l.account)}${l.party ? `<div class="small text-muted">${esc(l.party)}</div>` : ""}</td>
				<td class="text-right">${l.debit ? esc(format_currency(l.debit)) : ""}</td>
				<td class="text-right">${l.credit ? esc(format_currency(l.credit)) : ""}</td>
				<td>${esc(l.cost_center || "")}</td><td>${esc(l.station || l.project || "")}</td></tr>`
			)
			.join("");
		frappe.msgprint({
			title: __("Entry it will post"),
			message: `<table class="table table-sm"><thead><tr><th>${esc(__("Account"))}</th>
				<th class="text-right">${esc(__("Debit"))}</th><th class="text-right">${esc(__("Credit"))}</th>
				<th>${esc(__("Cost Center"))}</th><th>${esc(__("Station"))}</th></tr></thead><tbody>${rows}</tbody></table>`,
			wide: true,
		});
	}

	confirm(item) {
		frappe.confirm(__("Confirm {0} from {1}? The entry posts now.", [format_currency(item.amount), item.party || item.name]), async () => {
			await frappe.call({ method: `${SP_CF_API}.confirm`, args: { doctype: item.doctype, name: item.name }, freeze: true });
			frappe.show_alert({ message: __("Confirmed."), indicator: "green" });
			this.refresh();
		});
	}

	reject(item) {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			async ({ reason }) => {
				await frappe.call({
					method: `${SP_CF_API}.reject`,
					args: { doctype: item.doctype, name: item.name, reason },
					freeze: true,
				});
				frappe.show_alert({ message: __("Rejected: the recorder is told."), indicator: "orange" });
				this.refresh();
			},
			__("Reject"),
			__("Reject")
		);
	}

	bulk() {
		const items = this.$body
			.find(".sp-cf-check:checked")
			.map((_, el) => ({ doctype: el.dataset.doctype, name: el.dataset.name }))
			.get();
		if (!items.length) {
			frappe.msgprint(__("Select the items you checked against the statement."));
			return;
		}
		frappe.confirm(__("Confirm {0} items? Their entries post now.", [items.length]), async () => {
			const { message: key } = await frappe.call({ method: `${SP_CF_API}.bulk_confirm`, args: { items } });
			this.watch(key, items.length);
		});
	}

	async watch(key, total) {
		const { message: result } = await frappe.call(`${SP_CF_API}.bulk_result`, { key });
		frappe.show_progress(__("Confirming"), result.results.length, total);
		if (!result.done) {
			setTimeout(() => this.watch(key, total), SP_CF_POLL_MS);
			return;
		}
		frappe.hide_progress();
		const failed = result.results.filter((r) => !r.ok);
		const esc = frappe.utils.escape_html;
		frappe.msgprint({
			title: __("Bulk confirmation"),
			indicator: failed.length ? "orange" : "green",
			message:
				`<p>${esc(__("{0} confirmed, {1} failed.", [result.results.length - failed.length, failed.length]))}</p>` +
				failed.map((r) => `<div>${esc(r.name)}: ${esc(r.error || "")}</div>`).join(""),
		});
		this.refresh();
	}
}

$(`<style>.sp-cf-thumb { height: 32px; border-radius: 4px; }</style>`).appendTo(document.head);
