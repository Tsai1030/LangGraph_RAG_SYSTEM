"""Top-level namespace for self-contained feature modules.

Each subpackage under app.modules.* must be importable in isolation:
its only allowed imports are itself + app.config + app.search_database
(or app.database where authoritative) + app.core.* + app.models.user.
Reaching into app.rag.*, app.graph.*, or other RAG-specific packages
is forbidden — keeps modules portable should they ever spin out.
"""
