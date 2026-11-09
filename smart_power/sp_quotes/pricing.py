"""Prices for quotes (SP-30): the sale price for the customer's tier, the cost and the price age.

    get_price(item_code, tier, date) -> {price, cost, age_days, is_stale, ...}

The quote builder (SP-57), the indicative price (SP-49) and the stale-price rule (SP-63) use
this. The model lives in smart_power.sp_stock.prices.
"""

from smart_power.sp_stock.prices import get_price

__all__ = ["get_price"]
