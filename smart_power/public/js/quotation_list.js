// Q1 quotes list (SP-64): the latest version of each quote by default (a toggle shows every
// version), the quote creator's own quotes first, and the Smart Power status as the indicator.
// The margin column is the cost permlevel's, so Frappe leaves it out for the follow-up roles.
// The columns, fields and saved views are set on the server (smart_power.sp_sales.quote_list).
(function () {
	const settings = (frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {});
	const SP_Q_CREATOR_ROLES = ["SP Quote Creator", "SP System Designer"];
	const SP_Q_ADMIN_ROLES = ["SP Admin", "System Manager"];
	const SP_Q_COLORS = {
		Draft: "gray",
		Sent: "blue",
		"Needs repricing": "orange",
		Approved: "green",
		Superseded: "gray",
		Lost: "red",
		Expired: "orange",
	};
	const LATEST = "sp_is_latest";

	settings.add_fields = [...new Set([...(settings.add_fields || []), "sp_status", LATEST, "sp_version"])];

	// the first time the list opens: the latest versions, and a quote creator's own quotes
	const creator =
		SP_Q_CREATOR_ROLES.some((r) => frappe.user.has_role(r)) &&
		!SP_Q_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
	settings.filters = [[LATEST, "=", 1], ...(creator ? [["sp_quote_creator", "=", frappe.session.user]] : [])];

	// the margin is the quote creator's own (SP-35): another creator's row shows it blank
	const admin = SP_Q_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
	settings.add_fields.push("sp_quote_creator");
	settings.formatters = Object.assign(settings.formatters || {}, {
		sp_margin_pct(value, df, doc) {
			if (!admin && doc.sp_quote_creator && doc.sp_quote_creator !== frappe.session.user) return "";
			return frappe.format(value, df, null, doc);
		},
	});

	const erpnext_indicator = settings.get_indicator;
	settings.get_indicator = function (doc) {
		if (doc.sp_status) {
			return [__(doc.sp_status), SP_Q_COLORS[doc.sp_status] || "gray", `sp_status,=,${doc.sp_status}`];
		}
		return erpnext_indicator ? erpnext_indicator(doc) : undefined;
	};

	const erpnext_onload = settings.onload;
	settings.onload = function (listview) {
		if (erpnext_onload) erpnext_onload(listview);
		listview.sp_versions_button = listview.page.add_inner_button(__("All Versions"), () => sp_q_toggle_versions(listview));
		if (frappe.model.can_create("Quotation")) {
			listview.page.add_action_item(__("Duplicate for Customer"), () => {
				const selected = listview.get_checked_items(true);
				if (selected.length !== 1) {
					frappe.msgprint(__("Select one quote to duplicate."));
					return;
				}
				sp.sales.duplicate_quote(selected[0]);
			});
		}
	};

	const erpnext_refresh = settings.refresh;
	settings.refresh = function (listview) {
		if (erpnext_refresh) erpnext_refresh(listview);
		if (listview.sp_versions_button) {
			listview.sp_versions_button.text(sp_q_latest_only(listview) ? __("All Versions") : __("Latest Versions Only"));
		}
	};

	function sp_q_latest_only(listview) {
		return (listview.filter_area?.get() || []).some((f) => f[1] === LATEST && cint(f[3]) === 1); // sp-allow-number: a filter row is [doctype, field, op, value]
	}

	async function sp_q_toggle_versions(listview) {
		if (sp_q_latest_only(listview)) {
			await listview.filter_area.remove(LATEST);
		} else {
			await listview.filter_area.add([["Quotation", LATEST, "=", 1]]);
		}
	}
})();
