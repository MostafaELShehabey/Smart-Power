// Site photos (SP-96, SP-53): the photos and videos attached to a site log or a station, each with
// a "Usable for marketing" tick. Ticked ones appear in the media library (MK3). The rules are on
// the server (smart_power.sp_site.site_log.photos / set_marketing).
frappe.provide("smart_power");

const SP_SITE_PHOTOS_API = "smart_power.sp_site.site_log";
const SP_SITE_VIDEO = /\.(mp4|mov)$/i;

smart_power.site_photos = async function (frm, fieldname, empty_new) {
	const field = frm.fields_dict[fieldname];
	if (!field) return;
	const $box = field.$wrapper.empty();
	if (frm.is_new()) {
		$box.html(`<div class="text-muted small">${frappe.utils.escape_html(empty_new)}</div>`);
		return;
	}
	const { message: files } = await frappe.call(`${SP_SITE_PHOTOS_API}.photos`, {
		doctype: frm.doctype,
		name: frm.doc.name,
	});
	if (!files.length) {
		$box.html(
			`<div class="text-muted small">${frappe.utils.escape_html(__("No photos yet: attach them in the sidebar."))}</div>`
		);
		return;
	}
	const can_tag = frappe.model.can_write(frm.doctype) && !frm.doc.__onload?.sp_read_only;
	const $grid = $('<div class="d-flex flex-wrap"></div>').appendTo($box);
	files.forEach((f) => {
		const video = SP_SITE_VIDEO.test(f.file_name || "");
		const $card = $(`<div class="mr-3 mb-3 text-center sp-site-photo" style="width: 140px;">
			<a target="_blank" rel="noopener"></a>
			<label class="small d-block mt-1"><input type="checkbox"> ${frappe.utils.escape_html(__("Usable for marketing"))}</label>
		</div>`).appendTo($grid);
		const $media = $(video ? "<video muted preload='metadata'></video>" : "<img>")
			.addClass("rounded border")
			.css({ width: "140px", height: "100px", "object-fit": "cover" })
			.attr(video ? "title" : "alt", f.file_name)
			.attr("src", f.file_url);
		$card.find("a").attr("href", f.file_url).append($media);
		$card
			.find("input")
			.prop("checked", !!f.sp_usable_for_marketing)
			.prop("disabled", !can_tag)
			.on("change", async (e) => {
				await frappe.call({
					method: `${SP_SITE_PHOTOS_API}.set_marketing`,
					args: { file: f.name, usable: e.target.checked ? 1 : 0 },
				});
				frappe.show_alert({ message: __("Saved"), indicator: "green" });
			});
	});
};
