// Q2 Quote Builder (SP-57): mounts the Vue page on the Frappe page.
import { createApp } from "vue";
import QuoteBuilder from "./quote_builder/QuoteBuilder.vue";

window.sp = window.sp || {};
sp.quote_builder = {
	mount(page, name) {
		// back on the same quote with unsaved changes: keep them on screen
		if (page.sp_builder_name === name && page.sp_builder_dirty?.()) return;
		if (page.sp_builder) page.sp_builder.unmount();
		page.sp_builder_name = name;
		$(page.main).empty();
		const root = $("<div></div>").appendTo(page.main).get(0);
		page.sp_builder = createApp(QuoteBuilder, { page, name });
		page.sp_builder.config.globalProperties.__ = window.__;
		page.sp_builder.mount(root);
	},
};
