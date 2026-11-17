// F1 Follow-up board (SP-66): the cases by stage. A card shows the customer, the quote total at
// sale price, the last call, the next call and how long the quote is still valid (red under a
// day). A card is dragged only to the columns the workflow allows this user; Won and Lost open
// their dialogs. The rules are on the server (smart_power.sp_sales.board).

const SP_FB_API = "smart_power.sp_sales.board";
const SP_FB_TICK_MS = 60000; // sp-allow-number: the expiry countdown redraws every minute
const SP_FB_REFRESH_MS = 1500; // sp-allow-number: realtime updates are grouped for this long
const SP_FB_CHIPS = { red: "red", ok: "green", expired: "gray" };

frappe.pages["sp-followup-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Follow-up Board"),
		single_column: true,
	});
	wrapper.sp_followup_board = new SPFollowupBoard(page);
};

frappe.pages["sp-followup-board"].on_page_show = function (wrapper) {
	wrapper.sp_followup_board && wrapper.sp_followup_board.refresh();
};

// milliseconds until a server datetime, both read in the site's time zone (the browser's may differ)
function sp_fb_ms_until(datetime) {
	return frappe.datetime.str_to_obj(datetime) - frappe.datetime.str_to_obj(frappe.datetime.now_datetime());
}

// "2d 5h", "20h 10m" or "45m" until the quote expires
function sp_fb_left(expires_at) {
	const ms = sp_fb_ms_until(expires_at);
	if (ms <= 0) return __("Expired");
	const minutes = Math.floor(ms / 60000); // sp-allow-number: ms per minute
	const days = Math.floor(minutes / 1440); // sp-allow-number: minutes per day
	const hours = Math.floor((minutes % 1440) / 60); // sp-allow-number: minutes per day / hour
	if (days) return __("{0}d {1}h", [days, hours]);
	if (hours) return __("{0}h {1}m", [hours, minutes % 60]); // sp-allow-number: minutes per hour
	return __("{0}m", [minutes]);
}

function sp_fb_expiry_state(card) {
	// the server's state, kept up to date between refreshes as time passes
	if (!card.expires_at) return null;
	const ms = sp_fb_ms_until(card.expires_at);
	if (ms <= 0) return "expired";
	return ms < 86400000 ? "red" : "ok"; // sp-allow-number: ms per day
}

class SPFollowupBoard {
	constructor(page) {
		this.page = page;
		this.view = "board";
		this.cards = [];
		this.make_filters();
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$toggle = this.page.add_inner_button(__("List view"), () => {
			this.view = this.view === "board" ? "list" : "board";
			this.$toggle.text(this.view === "board" ? __("List view") : __("Board view"));
			this.render();
		});
		this.$body = $('<div class="sp-fb-body"></div>').appendTo(this.page.main);
		this.add_styles();
		frappe.realtime.doctype_subscribe("SP Case");
		frappe.realtime.on("sp_case_update", () => {
			clearTimeout(this.pending);
			this.pending = setTimeout(() => this.refresh(), SP_FB_REFRESH_MS);
		});
		setInterval(() => this.view === "board" && this.$body.is(":visible") && this.tick(), SP_FB_TICK_MS);
		this.refresh();
	}

	make_filters() {
		const on_change = () => this.refresh();
		const list_query = (list_name) => () => ({ filters: { list_name, is_active: 1 } });
		this.filters = {
			owner: this.page.add_field({
				fieldname: "owner",
				fieldtype: "Link",
				options: "User",
				label: __("Follow-up Owner"),
				change: on_change,
			}),
			channel: this.page.add_field({
				fieldname: "channel",
				fieldtype: "Select",
				options: ["", "Showroom", "Call", "Marketing"].map((v) => ({ value: v, label: __(v) })),
				label: __("Channel"),
				change: on_change,
			}),
			system_type: this.page.add_field({
				fieldname: "system_type",
				fieldtype: "Link",
				options: "SP List Value",
				label: __("System Type"),
				get_query: list_query("System Type"),
				change: on_change,
			}),
			region: this.page.add_field({
				fieldname: "region",
				fieldtype: "Link",
				options: "SP List Value",
				label: __("Region"),
				get_query: list_query("Region"),
				change: on_change,
			}),
		};
	}

	filter_values() {
		const values = {};
		Object.entries(this.filters).forEach(([key, field]) => {
			if (field.get_value()) values[key] = field.get_value();
		});
		return values;
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_FB_API}.board`, { filters: this.filter_values() });
		this.columns = message.columns;
		this.cards = message.cards;
		// only the follow-up lead and the admin pick another owner
		$(this.filters.owner.wrapper).toggle(!!message.sees_all);
		this.render();
	}

	render() {
		this.$body.empty();
		if (this.view === "list") this.render_list();
		else this.render_board();
	}

	render_board() {
		const esc = frappe.utils.escape_html;
		const $board = $('<div class="sp-fb-board"></div>').appendTo(this.$body);
		this.columns.forEach((col) => {
			const cards = this.cards.filter((c) => c.column === col.key);
			const $col = $(`<div class="sp-fb-column" data-column="${esc(col.key)}">
				<div class="sp-fb-column-head">${esc(col.label)} <span class="badge">${cards.length}</span></div>
				<div class="sp-fb-cards"></div>
			</div>`).appendTo($board);
			cards.forEach((card) => this.make_card(card).appendTo($col.find(".sp-fb-cards")));
			this.bind_drop($col, col);
		});
	}

	make_card(card) {
		const esc = frappe.utils.escape_html;
		const line = (label, value) =>
			value ? `<div class="small"><span class="text-muted">${esc(label)}:</span> ${esc(value)}</div>` : "";
		const $card = $(`<div class="sp-fb-card" draggable="${card.moves.length ? "true" : "false"}"
			data-case="${esc(card.name)}">
			<div class="d-flex justify-content-between">
				<b>${esc(card.customer_name || card.customer)}</b>
				<span class="sp-fb-expiry"></span>
			</div>
			<div class="small text-muted">${esc([card.name, card.mobile].filter(Boolean).join(" · "))}</div>
			${line(__("System"), card.systems.join("، "))}
			${card.total ? line(__("Total"), format_currency(card.total, card.currency)) : ""}
			${line(__("Quote Creator"), card.quote_creator_name)}
			${line(__("Last Call"), card.last_call)}
			${line(__("Next Call"), card.next_call_at && frappe.datetime.str_to_user(card.next_call_at))}
			${line(__("Follow-up Owner"), card.follow_up_owner_name)}
		</div>`);
		this.draw_expiry($card, card);
		$card.on("click", () => frappe.set_route("Form", "SP Case", card.name));
		$card.on("dragstart", (e) => {
			this.dragging = card;
			e.originalEvent.dataTransfer.setData("text/plain", card.name);
			this.$body.find(".sp-fb-column").each((_, el) => {
				$(el).toggleClass("sp-fb-allowed", card.moves.includes(el.dataset.column));
			});
		});
		$card.on("dragend", () => this.$body.find(".sp-fb-column").removeClass("sp-fb-allowed sp-fb-over"));
		return $card;
	}

	draw_expiry($card, card) {
		const state = sp_fb_expiry_state(card);
		const $chip = $card.find(".sp-fb-expiry").empty();
		if (!state) return;
		$chip.append(
			`<span class="indicator-pill ${SP_FB_CHIPS[state]}">${frappe.utils.escape_html(
				sp_fb_left(card.expires_at)
			)}</span>`
		);
	}

	tick() {
		this.cards.forEach((card) => {
			const $card = this.$body.find(`.sp-fb-card[data-case="${CSS.escape(card.name)}"]`);
			if ($card.length) this.draw_expiry($card, card);
		});
	}

	bind_drop($col, col) {
		$col.on("dragover", (e) => {
			if (this.dragging && this.dragging.moves.includes(col.key)) {
				e.preventDefault();
				$col.addClass("sp-fb-over");
			}
		});
		$col.on("dragleave", () => $col.removeClass("sp-fb-over"));
		$col.on("drop", (e) => {
			e.preventDefault();
			const card = this.dragging;
			this.dragging = null;
			if (!card || card.column === col.key) return;
			if (!card.moves.includes(col.key)) {
				frappe.show_alert({ message: __("This move is not allowed."), indicator: "red" });
				return;
			}
			this.move(card, col.key);
		});
	}

	async move(card, to_column) {
		if (to_column === "won") return this.won_dialog(card);
		if (to_column === "lost") return this.lost_dialog(card);
		await frappe.call({
			method: `${SP_FB_API}.move_case`,
			args: { case: card.name, to_column },
			freeze: true,
		});
		this.refresh();
	}

	// a drop on Won: the customer intends to proceed; the deposit marks the win (SP-70)
	won_dialog(card) {
		sp.sales.intends_to_proceed(card.name, () => this.refresh());
	}

	lost_dialog(card) {
		const dialog = new frappe.ui.Dialog({
			title: __("Mark Lost"),
			fields: [
				{
					fieldname: "lost_reason",
					fieldtype: "Link",
					label: __("Lost Reason"),
					options: "SP List Value",
					reqd: 1,
					get_query: () => ({ filters: { list_name: "Lost Reason", is_active: 1 } }),
				},
				{ fieldname: "lost_note", fieldtype: "Small Text", label: __("Lost Note") },
			],
			primary_action_label: __("Mark Lost"),
			primary_action: async (values) => {
				await frappe.call({
					method: "smart_power.sp_sales.followup.mark_lost",
					args: { case: card.name, ...values },
					freeze: true,
				});
				dialog.hide();
				this.refresh();
			},
		});
		dialog.show();
	}

	render_list() {
		const esc = frappe.utils.escape_html;
		if (!this.cards.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("No cases here."))}</div>`);
			return;
		}
		const labels = Object.fromEntries(this.columns.map((c) => [c.key, c.label]));
		const rows = this.cards
			.map(
				(c) => `<tr data-case="${esc(c.name)}">
				<td><a href="/app/sp-case/${encodeURIComponent(c.name)}">${esc(c.name)}</a></td>
				<td>${esc(c.customer_name || c.customer)}</td>
				<td>${esc(c.mobile || "")}</td>
				<td>${esc(labels[c.column] || c.status)}</td>
				<td>${esc(c.systems.join("، "))}</td>
				<td class="text-right">${c.total ? esc(format_currency(c.total, c.currency)) : ""}</td>
				<td>${esc(c.last_call || "")}</td>
				<td>${esc(c.next_call_at ? frappe.datetime.str_to_user(c.next_call_at) : "")}</td>
				<td>${c.expires_at ? esc(sp_fb_left(c.expires_at)) : ""}</td>
				<td>${esc(c.follow_up_owner_name || "")}</td>
			</tr>`
			)
			.join("");
		this.$body.append(`<table class="table table-hover table-sm"><thead><tr>
			<th>${esc(__("Case"))}</th><th>${esc(__("Customer"))}</th><th>${esc(__("Mobile"))}</th>
			<th>${esc(__("Status"))}</th><th>${esc(__("System"))}</th><th class="text-right">${esc(__("Total"))}</th>
			<th>${esc(__("Last Call"))}</th><th>${esc(__("Next Call"))}</th><th>${esc(__("Expires In"))}</th>
			<th>${esc(__("Follow-up Owner"))}</th>
		</tr></thead><tbody>${rows}</tbody></table>`);
	}

	add_styles() {
		if (document.getElementById("sp-fb-style")) return;
		$(`<style id="sp-fb-style">
			.sp-fb-board { display: flex; gap: var(--padding-md); overflow-x: auto; align-items: flex-start; }
			.sp-fb-column { flex: 0 0 260px; background: var(--subtle-fg); border-radius: var(--border-radius-md);
				padding: var(--padding-sm); min-height: 200px; }
			.sp-fb-column-head { font-weight: bold; margin-bottom: var(--padding-sm); }
			.sp-fb-allowed { outline: 2px dashed var(--primary); }
			.sp-fb-over { background: var(--control-bg); }
			.sp-fb-card { background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: var(--border-radius); padding: var(--padding-sm); margin-bottom: var(--padding-sm);
				cursor: pointer; }
			.sp-fb-card[draggable="true"] { cursor: grab; }
		</style>`).appendTo(document.head);
	}
}
