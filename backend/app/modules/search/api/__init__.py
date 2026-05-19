"""SEARCH module HTTP layer.

Router prefix convention:
    Each router declares ONLY its module-local prefix
    (e.g. "/search/generation", "/admin/search-csc"). main.py adds
    "/api" once when mounting. This avoids accidental double prefix
    like /api/api/search/... that would happen if the routers also
    prepended /api themselves.

All routers depend on app.core.dependencies — JWT auth + permission
gating live in the central place, not duplicated here.
"""
