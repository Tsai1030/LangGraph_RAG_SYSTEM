"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { tryRestoreSession } from "@/lib/auth";
import { useAuthStore } from "@/store/authStore";
import Sidebar from "@/components/layout/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const [ready, setReady] = useState(false);

  useEffect(() => {
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
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--sidebar-bg)" }}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin-custom" />
          <span className="text-slate-500 text-sm">載入中...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--content-bg)" }}>
      {/* Sidebar */}
      <div className="w-64 shrink-0 flex flex-col" style={{ background: "var(--sidebar-bg)" }}>
        <Sidebar />
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {children}
      </main>
    </div>
  );
}
