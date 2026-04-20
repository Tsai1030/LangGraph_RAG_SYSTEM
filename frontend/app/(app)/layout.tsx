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
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const init = async () => {
      if (!accessToken) {
        const ok = await tryRestoreSession();
        if (!ok) {
          router.replace("/login");
          return;
        }
        // 從 cookie 還原 session（頁面重整或首次進入）→ 固定從歡迎頁開始
        router.replace("/new");
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
      {/* Sidebar — animated width */}
      <div
        className="shrink-0 flex flex-col overflow-hidden"
        style={{
          background: "#09090b",
          width: collapsed ? "56px" : "256px",
          transition: "width 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {children}
      </main>
    </div>
  );
}
