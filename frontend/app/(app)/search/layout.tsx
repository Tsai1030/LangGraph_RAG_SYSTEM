"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

/**
 * Permission gate for /search/*.
 *
 * Reads the user out of auth store (populated by (app)/layout's /auth/me
 * call). If search_enabled is false, redirect to /search/no-access.
 *
 * Why client-side rather than middleware:
 *   - RAG already does auth client-side in (app)/layout via
 *     tryRestoreSession. Matching that pattern keeps the mental model
 *     consistent.
 *   - The /no-access page itself must NOT be redirected, otherwise users
 *     without permission would be bounced in a loop. We skip the check
 *     for that path.
 *
 * Critical: we MUST not render `children` until we've confirmed the user
 * has permission. Initial mount has user=undefined (still loading from
 * /auth/me), and rendering GenerateView in that window briefly paints
 * the wizard's first step before the redirect fires — looks like a UI
 * flash. So we hold the children behind a spinner until user is loaded
 * and search_enabled is true.
 */
export default function SearchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const isNoAccessPage = pathname?.startsWith("/search/no-access");

  useEffect(() => {
    if (!user) return;   // still loading from (app)/layout
    if (isNoAccessPage) return;   // never redirect away from the fallback page
    if (!user.search_enabled) {
      router.replace("/search/no-access");
    }
  }, [user, isNoAccessPage, router]);

  // /no-access is always renderable — it's the destination of denied users.
  if (isNoAccessPage) return <>{children}</>;

  // Loading user, or user lacks permission and the redirect is about to
  // fire — show a quiet spinner instead of children.
  if (!user || !user.search_enabled) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="size-6 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast" />
      </div>
    );
  }

  return <>{children}</>;
}
