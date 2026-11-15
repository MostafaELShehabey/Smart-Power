"""SP-175: stock is reserved against the Sales Order from the deposit."""

from smart_power.sp_stations.setup import enable_stock_reservation


def execute():
	enable_stock_reservation()
