"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, BarChart3, Database, Users } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/admin", label: "概覽", icon: BarChart3, exact: true },
  { href: "/admin/users", label: "使用者", icon: Users },
  { href: "/admin/vector", label: "向量庫", icon: Database },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    // user 還沒載入時不動作；載入後若非 admin 立刻踢走
    if (user && user.role !== "admin") {
      router.replace("/new");
    }
  }, [user, router]);

  if (!user) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="size-6 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast" />
      </div>
    );
  }

  if (user.role !== "admin") {
    // useEffect 會處理跳轉，先顯示空白避免閃爍
    return null;
  }

  const isActive = (tab: typeof TABS[number]) =>
    tab.exact ? pathname === tab.href : pathname.startsWith(tab.href);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <header className="shrink-0 border-b border-zinc-200 bg-white">
        <div className="pl-14 pr-4 py-3 md:px-6 flex items-center gap-4">
          <Link
            href="/new"
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 transition-colors"
          >
            <ArrowLeft size={13} />
            返回
          </Link>
          <span className="h-4 w-px bg-zinc-200" />
          <h1 className="text-sm font-semibold text-zinc-900">管理後台</h1>
        </div>
        <nav className="px-4 flex items-center gap-1 overflow-x-auto">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = isActive(tab);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2.5 text-[13px] border-b-2 transition-colors whitespace-nowrap",
                  active
                    ? "border-zinc-900 text-zinc-900 font-medium"
                    : "border-transparent text-zinc-500 hover:text-zinc-900"
                )}
              >
                <Icon size={14} />
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </header>

      {/* Main scrollable content */}
      <main className="flex-1 overflow-auto bg-zinc-50">
        <div className="max-w-6xl mx-auto p-6">{children}</div>
      </main>
    </div>
  );
}
