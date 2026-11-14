"""SP-62: the Smart Power letterhead becomes the site's default letterhead too (ERPNext copies
it onto new quotes), unless the admin chose another; draft quotes with the stock one follow."""

from smart_power.sp_core.setup.print_setup import ensure_letter_head, use_our_letter_head_on_drafts


def execute():
	ensure_letter_head()
	use_our_letter_head_on_drafts()
