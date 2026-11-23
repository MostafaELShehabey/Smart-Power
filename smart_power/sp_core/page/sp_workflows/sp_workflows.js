// X5 Workflows (SP-133): every record's lifecycle. Cases and stations open in Frappe's Workflow
// Builder; the records whose statuses the code sets are shown read-only. Locked states and steps
// (smart_power.sp_core.workflows.GUARD) carry a lock: the system needs them.
const SP_WF = "smart_power.sp_core.workflows";

frappe.pages["sp-workflows"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Workflows"), single_column: true });
	wrapper.sp_workflows = new SPWorkflows(page);
};

frappe.pages["sp-workflows"].on_page_show = function (wrapper) {
	wrapper.sp_workflows.refresh();
};

class SPWorkflows {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="sp-wf"><div class="sp-wf-list"></div><div class="sp-wf-view"></div></div>').appendTo(page.main);
		this.$body.on("click", "[data-flow]", (e) => this.open(e.currentTarget.dataset.flow));
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_WF}.flows`);
		const esc = frappe.utils.escape_html;
		const group = (editable) =>
			message
				.filter((f) => f.editable === editable)
				.map((f) => `<button class="btn btn-sm ${this.current === f.key ? "btn-primary" : "btn-default"}" data-flow="${esc(f.key)}">${esc(f.label)}</button>`)
				.join("");
		this.$body.find(".sp-wf-list").html(`
			<p class="sp-wf-head">${__("Edited in the Workflow Builder")}</p><div class="sp-wf-buttons">${group(true)}</div>
			<p class="sp-wf-head">${__("Set by the system (read-only)")}</p><div class="sp-wf-buttons">${group(false)}</div>`);
		if (this.current) this.open(this.current);
	}

	async open(key) {
		this.current = key;
		this.$body.find("[data-flow]").each((_, b) => b.classList.toggle("btn-primary", b.dataset.flow === key));
		this.$body.find("[data-flow]").each((_, b) => b.classList.toggle("btn-default", b.dataset.flow !== key));
		const { message: d } = await frappe.call(`${SP_WF}.diagram`, { key });
		const esc = frappe.utils.escape_html;
		const lock = frappe.utils.icon("lock", "xs");
		const states = d.states
			.map(
				(s) => `<span class="sp-wf-state ${s.style ? "sp-wf-" + s.style.toLowerCase() : ""}" title="${s.by_system ? esc(__("Only the system moves a record here")) : ""}">
				${s.locked ? lock : ""} ${esc(s.label)}${s.by_system ? " ⚙" : ""}</span>`
			)
			.join('<span class="sp-wf-arrow">←</span>');
		const steps = d.transitions.length
			? `<table class="table table-sm table-bordered"><thead><tr><th>${__("From")}</th><th>${__("Action")}</th><th>${__("To")}</th><th>${__("Who")}</th></tr></thead><tbody>${d.transitions
					.map((t) => `<tr><td>${esc(t.from)}</td><td>${t.locked ? lock + " " : ""}${esc(t.action)}</td><td>${esc(t.to)}</td><td>${t.roles.map(esc).join("، ")}</td></tr>`)
					.join("")}</tbody></table>`
			: "";
		const actions = d.editable && d.workflow
			? `<button class="btn btn-primary btn-sm" data-open="${esc(d.workflow)}">${__("Open in the Workflow Builder")}</button>`
			: "";
		const note = d.editable
			? __("A locked state or step is needed by the system: it cannot be removed or renamed. A new state goes before a state marked ⚙, which only the system sets.")
			: __("The system's code moves these records from status to status, so they have no editable workflow.");
		this.$body.find(".sp-wf-view").html(`<h4>${esc(d.label)}</h4><p class="text-muted">${note}</p>
			<div class="sp-wf-states">${states}</div>${steps}<div>${actions}</div>`);
		this.$body.find("[data-open]").on("click", (e) => frappe.set_route("workflow-builder", e.currentTarget.dataset.open));
	}
}

frappe.dom.set_style(`
.sp-wf-head { margin: 12px 0 6px; font-weight: bold; }
.sp-wf-buttons { display: flex; flex-wrap: wrap; gap: 6px; }
.sp-wf-view { margin-top: 16px; }
.sp-wf-states { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 12px 0; }
.sp-wf-state { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 12px; border: 1px solid var(--border-color); background: var(--card-bg); }
.sp-wf-success { background: var(--bg-green); }
.sp-wf-danger { background: var(--bg-red); }
.sp-wf-warning { background: var(--bg-orange); }
.sp-wf-primary, .sp-wf-info { background: var(--bg-blue); }
.sp-wf-arrow { color: var(--text-muted); }
`);
