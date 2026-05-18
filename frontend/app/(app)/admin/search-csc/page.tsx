"use client";

import { CscAdminView } from "@/components/search/csc-admin-view";

/**
 * /admin/search-csc — 中鋼盤價 (CSC) admin editor.
 *
 * Wrapped in admin/layout.tsx — get_current_admin enforced at API level
 * + role check at layout level. CscAdminView handles its own loading
 * states via TanStack Query.
 */
export default function AdminSearchCscPage() {
  return <CscAdminView />;
}
