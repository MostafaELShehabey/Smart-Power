"""SP-30: add the four price lists and the price categories to sites set up before this change."""

from smart_power.sp_stock.prices import seed_price_categories, seed_price_lists


def execute():
	# The price-age category fields ship as custom-field fixtures, and migrate syncs fixtures
	# only after the patches. Sync them first, or this patch reads a column that is not there
	# yet and stops the migrate on every existing site.
	from frappe.utils.fixtures import sync_fixtures

	sync_fixtures("smart_power")
	seed_price_lists()
	seed_price_categories()
