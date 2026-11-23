// T1 Design tools (SP-65): mounts the Vue page on the Frappe page.
import { createApp } from "vue";
import DesignTools from "./design_tools/DesignTools.vue";

window.sp = window.sp || {};
sp.design_tools = {
	mount(page, quote) {
		if (page.sp_tools && (!quote || page.sp_tools_quote === quote)) return; // keep what is on screen
		if (page.sp_tools) page.sp_tools.unmount();
		page.sp_tools_quote = quote;
		$(page.main).empty();
		const root = $("<div></div>").appendTo(page.main).get(0);
		page.sp_tools = createApp(DesignTools, { page, quote });
		page.sp_tools.config.globalProperties.__ = window.__;
		page.sp_tools.mount(root);
	},
};
