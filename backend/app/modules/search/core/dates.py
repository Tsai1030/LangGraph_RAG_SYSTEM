"""Shared date helpers.

Why a dedicated module? 豐興 only opens on Mondays — every weekly opening
price is keyed by the Monday of its week. The user can pick any meeting
date in the UI; the system must consistently fold that down to "the Monday
of that week" for fetch / persist / history lookup, otherwise Section 七
develops gaps and Tuesday/Wednesday rows.

Single source of truth lives here so adapter, orchestrator, and API agree.
"""
from __future__ import annotations

from datetime import date, timedelta


def opening_monday(d: date) -> date:
    """Return the Monday of the week containing `d`.

    >>> opening_monday(date(2026, 5, 12))   # Tuesday
    datetime.date(2026, 5, 11)
    >>> opening_monday(date(2026, 5, 11))   # Monday — itself
    datetime.date(2026, 5, 11)
    >>> opening_monday(date(2026, 5, 17))   # Sunday
    datetime.date(2026, 5, 11)
    """
    # weekday(): Monday=0, Sunday=6
    return d - timedelta(days=d.weekday())
