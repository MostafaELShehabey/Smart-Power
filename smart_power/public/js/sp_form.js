// The record pattern (SP-45), the same on every main record:
//   sp.form.register_primary(doctype, field, states)
//                              one primary button that follows the record's status
//   sp.form.status_bar(frm)    the workflow's stages as steps, the current one in gold; only the
//                              stages the user may move to next are clickable
//   sp.form.owner_chips(frm)   who owns it now (boot.sp_owner_fields); a chip's popover holds
//                              that role's history (from, to, date, reason, by whom)
// Voice notes (audio attachments) play where they are listed. Comments with @mentions,
// attachments and the field history (old → new, who, when) are Frappe's own timeline.
window.sp = window.sp || {};
sp.form = sp.form || {};

// states: {status: {label, action(frm)}}; applies(frm), if given, says which records use it.
// Registered after the doctype's own refresh, so the primary button replaces the toolbar's
// Submit; it is left alone while the form has unsaved edits.
sp.form.register_primary = function (doctype, field, states, applies) {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (frm.is_new() || frm.is_dirty() || (applies && !applies(frm))) return;
			const state = states[frm.doc[field]];
			if (state) frm.page.set_primary_action(state.label, () => state.action(frm));
		},
	});
};

// the history of one owner role on this record, as an escaped table
sp.form.owner_history_html = function (frm, kind) {
	const esc = frappe.utils.escape_html;
	const who = (user) => esc(user ? frappe.user.full_name(user) : "—");
	const rows = (frm.doc.owner_history || []).filter((r) => r.role_kind === kind);
	if (!rows.length) return `<div class="text-muted">${esc(__("No change yet: the first owner still holds it."))}</div>`;
	const head = [__("From"), __("To"), __("Date"), __("Reason"), __("Changed By")];
	return `<table class="table table-sm mb-0 sp-owner-history"><thead><tr>${head
		.map((h) => `<th>${esc(h)}</th>`)
		.join("")}</tr></thead><tbody>${rows
		.map(
			(r) => `<tr><td>${who(r.from_user)}</td><td>${who(r.to_user)}</td>
				<td class="text-nowrap">${esc(frappe.datetime.str_to_user(r.from_date) || "")}</td>
				<td>${esc(r.reason || "")}</td><td>${who(r.changed_by)}</td></tr>`
		)
		.join("")}</tbody></table>`;
};

// a chip per owner; clicking it opens that role's history in a popover (closed by clicking away)
sp.form.owner_chips = function (frm, $row) {
	const esc = frappe.utils.escape_html;
	const owners = (frappe.boot.sp_owner_fields || {})[frm.doctype] || {};
	Object.entries(owners).forEach(([field, kind]) => {
		const user = frm.doc[field];
		const label = __(frappe.meta.get_label(frm.doctype, field, frm.doc.name));
		$(`<button type="button" class="btn btn-xs btn-default sp-owner-chip">
			${esc(label)}: <b>${esc(user ? frappe.user.full_name(user) : "—")}</b></button>`)
			.appendTo($row)
			.popover({
				trigger: "focus",
				placement: "bottom",
				html: true,
				sanitize: false, // the content is escaped above; the default allow-list drops tables
				customClass: "sp-owner-popover",
				title: () => esc(__("{0}: history", [label])),
				content: () => sp.form.owner_history_html(frm, kind),
			});
	});
};

sp.form.status_bar = async function (frm) {
	frm.$wrapper.find(".sp-owner-chip").popover("dispose");
	frm.$wrapper.find(".sp-status-bar").remove();
	if (frm.is_new() || !frappe.workflow.get_state_fieldname(frm.doctype)) return;
	const workflow = frappe.workflow.workflows[frm.doctype];
	const current = frm.doc[workflow.workflow_state_field];
	const transitions = await frappe.workflow.get_transitions(frm.doc);
	const next = {};
	(transitions || []).forEach((t) => (next[t.next_state] = next[t.next_state] || t.action));
	const esc = frappe.utils.escape_html;
	const $bar = $('<div class="sp-status-bar d-flex flex-wrap align-items-center px-3 pt-2 mb-2"></div>');
	const $steps = $('<div class="sp-steps d-flex flex-wrap"></div>').appendTo($bar);
	workflow.states.forEach(({ state }) => {
		const action = state !== current && next[state];
		const kind = state === current ? "sp-step-current" : action ? "sp-step-next" : "sp-step-off";
		const $step = $(`<span class="sp-step ${kind}">${esc(__(state))}</span>`).appendTo($steps);
		if (!action) return;
		$step.attr({ role: "button", title: __(action) }).on("click", () =>
			frappe.confirm(__("{0}: move to {1}?", [__(action), __(state)]), async () => {
				await frappe.xcall("frappe.model.workflow.apply_workflow", { doc: frm.doc, action });
				frm.reload_doc();
			})
		);
	});
	sp.form.owner_chips(frm, $('<div class="sp-owners d-flex flex-wrap ms-auto"></div>').appendTo($bar));
	frm.$wrapper.find(".sp-status-bar").remove(); // a second refresh may have drawn one meanwhile
	$bar.prependTo(frm.layout.wrapper);
};

// Voice notes: an audio attachment gets a player where it is listed.
sp.form.AUDIO = /\.(mp3|m4a|ogg|oga|wav|webm|aac|amr|3gp)(\?|$)/i;
sp.form.voice_notes = function (frm) {
	frm.$wrapper.find(".attachment-row a[href], .timeline-item a[href]").each((_, a) => {
		const href = $(a).attr("href");
		if (!sp.form.AUDIO.test(href) || $(a).siblings("audio.sp-voice-note").length) return;
		$('<audio controls preload="none" class="sp-voice-note d-block mt-1"></audio>').attr("src", href).insertAfter(a);
	});
};

$(document).on("form-refresh", (e, frm) => {
	if (!frm) return;
	if ((frappe.boot.sp_owner_fields || {})[frm.doctype]) sp.form.status_bar(frm);
	setTimeout(() => sp.form.voice_notes(frm), 1500); // sp-allow-number: after the sidebar and timeline render
});
