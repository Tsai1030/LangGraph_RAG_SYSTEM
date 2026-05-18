"use client";

import { AdminUsageView } from "@/components/search/admin-usage-view";

/**
 * /admin/search-usage — per-user run counts for the SEARCH module.
 *
 * Polls /api/admin/search-usage every 30s (handled inside AdminUsageView
 * via TanStack Query refetchInterval). Admin-only via the parent layout.
 */
export default function AdminSearchUsagePage() {
  return <AdminUsageView />;
}
