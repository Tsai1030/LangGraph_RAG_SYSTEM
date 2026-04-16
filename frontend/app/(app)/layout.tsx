"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { tryRestoreSession } from "@/lib/auth";
import { useAuthStore } from "@/store/authStore";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // On mount, try to restore session via HttpOnly refresh token cookie
    const init = async () => {
      if (!accessToken) {
        const ok = await tryRestoreSession();
        if (!ok) {
          router.replace("/login");
          return;
        }
      }
      setReady(true);
    };
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <span className="text-gray-400 text-sm">載入中...</span>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      {/* Sidebar placeholder — Phase 5 */}
      <aside className="w-64 shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <span className="font-semibold text-gray-700 text-sm">營造知識助理</span>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {/* Conversation list — Phase 5 */}
        </div>
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">{children}</main>
    </div>
  );
}
