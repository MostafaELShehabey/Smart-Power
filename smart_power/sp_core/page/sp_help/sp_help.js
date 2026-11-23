// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Help (SP-162): the user's own guides (the admin sees all), each task step by step with its
// screen and video, and the one-page card to print.
frappe.pages["sp-help"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Help"), single_column: true });
	const $body = $('<div class="sp-help"></div>').appendTo(page.main);
	const esc = frappe.utils.escape_html;
	const list = (items) => (items.length ? `<ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "");
	frappe.call("smart_power.sp_core.guides.my_guides").then(({ message: guides }) => {
		if (!guides || !guides.length) {
			$body.html(`<p class="text-muted">${__("No guide is set for your roles yet. Ask the admin.")}</p>`);
			return;
		}
		guides.forEach((g) => {
			const $card = $(`
				<div class="frappe-card" style="padding: var(--padding-md); margin-bottom: var(--margin-lg);">
					<div class="flex justify-between align-center">
						<h3>${esc(g.title)}</h3>
						<button class="btn btn-default btn-sm sp-print">${__("Print Card")}</button>
					</div>
					${g.home ? `<p><b>${__("Your Home Page")}:</b> ${esc(g.home)}</p>` : ""}
					${g.menu ? `<p><b>${__("Your Menu")}:</b> ${esc(g.menu)}</p>` : ""}
					${g.screens.length ? `<p><b>${__("Your Screens")}:</b> ${g.screens.map(esc).join("، ")}</p>` : ""}
					<div class="sp-tasks"></div>
					<div class="row">
						<div class="col-sm-6"><h5>${__("Always")}</h5>${list(g.dos)}</div>
						<div class="col-sm-6"><h5>${__("Never")}</h5>${list(g.donts)}</div>
					</div>
				</div>`).appendTo($body);
			$card.find(".sp-print").on("click", () => {
				const args = new URLSearchParams({ doctype: "SP User Guide", name: g.name, format: "SP Quick Reference Card", trigger_print: 1 });
				window.open(`/printview?${args}`);
			});
			g.tasks.forEach((t) => {
				const $task = $(`
					<div style="margin-bottom: var(--margin-md);">
						<h5>${t.is_top ? "★ " : ""}${esc(t.task)}</h5>
						<ol>${t.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
					</div>`).appendTo($card.find(".sp-tasks"));
				if (t.screen) {
					$(`<button class="btn btn-default btn-xs">${__("Open", null, "action")}</button>`)
						.appendTo($task)
						.on("click", () => frappe.set_route(...t.screen.split("/")));
				}
				if (t.video_url) {
					$(`<a class="btn btn-default btn-xs" style="margin-inline-start: var(--margin-sm);" target="_blank" rel="noopener">${__("Watch the Video")}</a>`)
						.attr("href", t.video_url)
						.appendTo($task);
				}
			});
		});
	});
};
