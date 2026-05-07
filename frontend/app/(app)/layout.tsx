"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { tryRestoreSession } from "@/lib/auth";
import { useAuthStore } from "@/store/authStore";
import api from "@/lib/api";
import type { User } from "@/types";
import Sidebar from "@/components/layout/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const setUser = useAuthStore((s) => s.setUser);
  // 已有 token（剛從 /login 過來）→ 直接 ready，避免暗色 loading 閃一下
  // 沒 token（fresh page load）→ ready=false，等 tryRestoreSession 跑完
  const [ready, setReady] = useState(!!accessToken);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

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
        setReady(true);
      }
      // /auth/me 在背景跑，不阻塞 UI（即使失敗 profile section 也會 fallback）
      try {
        const { data } = await api.get<User>("/auth/me");
        setUser(data);
      } catch {
        // 忽略
      }
    };
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-dot-grid">
        <div className="flex flex-col items-center gap-3">
          <div className="size-8 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast" />
          <span className="text-zinc-500 text-sm">載入中…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--content-bg)" }}>
      {/* Desktop Sidebar — animated width, hidden on mobile */}
      <div
        className="hidden md:flex shrink-0 flex-col overflow-hidden"
        style={{
          background: "#09090b",
          width: collapsed ? "56px" : "256px",
          transition: "width 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      </div>

      {/* Mobile Sidebar Overlay */}
      {mobileOpen && (
        <div className="md:hidden">
          {/* Blur backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/30"
            onClick={() => setMobileOpen(false)}
          />
          {/* Sidebar panel slides in from left */}
          <div
            className="fixed left-0 top-0 bottom-0 z-50 flex flex-col overflow-hidden"
            style={{ width: "256px", background: "#09090b" }}
          >
            <Sidebar
              collapsed={false}
              onToggle={() => {}}
              onMobileClose={() => setMobileOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0 relative">
        {/* Mobile hamburger button — two lines (long + short) */}
        <button
          className="md:hidden absolute top-3 left-3 z-30 flex flex-col gap-[5px] p-2 rounded-md text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100 transition-colors"
          onClick={() => setMobileOpen(true)}
          aria-label="開啟選單"
        >
          <span className="block h-0.5 w-5 bg-current rounded-full" />
          <span className="block h-0.5 w-3 bg-current rounded-full" />
        </button>
        {children}
      </main>
    </div>
  );
}
