"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { KeyRound, Search, ShieldCheck, ToggleLeft, ToggleRight, UserCheck, UserX } from "lucide-react";
import api from "@/lib/api";
import type { AdminUserListOut, AdminUserOut } from "@/types/admin";
import { useAuthStore } from "@/store/authStore";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const normalized = /[Zz+]/.test(iso) ? iso : iso + "Z";
  return new Date(normalized).toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AdminUsersPage() {
  const me = useAuthStore((s) => s.user);
  const [list, setList] = useState<AdminUserListOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: 100 };
      if (search.trim()) params.search = search.trim();
      const { data } = await api.get<AdminUserListOut>("/admin/users", { params });
      setList(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onToggleActive = async (u: AdminUserOut) => {
    if (u.id === me?.id) return; // 防止關掉自己
    if (!confirm(u.is_active ? `確定要停用 ${u.email}？` : `確定要啟用 ${u.email}？`)) return;
    setBusyId(u.id);
    try {
      await api.patch(`/admin/users/${u.id}/active`, { is_active: !u.is_active });
      setToast(u.is_active ? `已停用 ${u.email}` : `已啟用 ${u.email}`);
      await load();
    } catch {
      setToast("操作失敗");
    } finally {
      setBusyId(null);
      setTimeout(() => setToast(null), 3000);
    }
  };

  const onToggleSearch = async (u: AdminUserOut) => {
    // 允許 admin 改自己 — 跟 is_active 不同 (鎖自己最差只是失去 search 功能)
    const next = !u.search_enabled;
    if (!confirm(next ? `開通 ${u.email} 的鋼筋盤價助理？` : `關閉 ${u.email} 的鋼筋盤價助理？`)) return;
    setBusyId(u.id);
    try {
      await api.patch(`/admin/users/${u.id}/search-permission`, { search_enabled: next });
      setToast(next ? `已開通 ${u.email}` : `已關閉 ${u.email}`);
      await load();
    } catch {
      setToast("操作失敗");
    } finally {
      setBusyId(null);
      setTimeout(() => setToast(null), 3000);
    }
  };

  const onResetPassword = async (u: AdminUserOut) => {
    if (!confirm(`寄送密碼重設信給 ${u.email}？`)) return;
    setBusyId(u.id);
    try {
      const { data } = await api.post<{ message: string }>(`/admin/users/${u.id}/reset-password`);
      setToast(data.message);
    } catch {
      setToast("寄送失敗");
    } finally {
      setBusyId(null);
      setTimeout(() => setToast(null), 4000);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900">使用者管理</h2>
          <p className="text-sm text-zinc-500 mt-0.5">
            {list ? `共 ${list.total} 位使用者` : "—"}
          </p>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="搜尋 email / 名稱"
            className="h-9 w-64 rounded-lg border border-zinc-200 bg-white pl-8 pr-3 text-sm outline-none focus:border-zinc-400"
          />
        </div>
      </div>

      {toast && (
        <div className="text-sm text-zinc-700 bg-zinc-100 border border-zinc-200 rounded-lg px-4 py-2">
          {toast}
        </div>
      )}

      <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-xs text-zinc-500">
              <tr>
                <th className="text-left font-medium px-4 py-3">Email</th>
                <th className="text-left font-medium px-4 py-3">名稱</th>
                <th className="text-left font-medium px-4 py-3">角色</th>
                <th className="text-left font-medium px-4 py-3">狀態</th>
                <th className="text-left font-medium px-4 py-3">鋼筋盤價</th>
                <th className="text-right font-medium px-4 py-3">對話數</th>
                <th className="text-left font-medium px-4 py-3">最後活動</th>
                <th className="text-right font-medium px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-zinc-500">
                    <span className="size-4 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast inline-block mr-2 align-middle" />
                    載入中…
                  </td>
                </tr>
              )}
              {!loading && list?.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-zinc-500">
                    沒有符合條件的使用者
                  </td>
                </tr>
              )}
              {list?.items.map((u) => (
                <tr key={u.id} className="border-t border-zinc-100 hover:bg-zinc-50/50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/admin/users/${u.id}`}
                      className="text-zinc-900 hover:underline"
                    >
                      {u.email}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-zinc-600">{u.display_name ?? "—"}</td>
                  <td className="px-4 py-3">
                    {u.role === "admin" ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-900 text-white text-xs">
                        <ShieldCheck size={11} />
                        admin
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-500">user</span>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {u.is_active ? (
                      <span className="inline-block whitespace-nowrap text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md">
                        啟用中
                      </span>
                    ) : (
                      <span className="inline-block whitespace-nowrap text-xs text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded-md">
                        已停用
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <button
                      onClick={() => onToggleSearch(u)}
                      disabled={busyId === u.id}
                      title={u.search_enabled ? "點擊關閉鋼筋盤價助理權限" : "點擊開通鋼筋盤價助理權限"}
                      className="inline-flex items-center gap-1 text-xs disabled:opacity-40 transition-colors"
                    >
                      {u.search_enabled ? (
                        <>
                          <ToggleRight size={20} className="text-emerald-600" />
                          <span className="text-emerald-700">開通</span>
                        </>
                      ) : (
                        <>
                          <ToggleLeft size={20} className="text-zinc-400" />
                          <span className="text-zinc-500">未開通</span>
                        </>
                      )}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right text-zinc-600 tabular-nums">
                    {u.conversation_count}
                  </td>
                  <td className="px-4 py-3 text-xs text-zinc-500">
                    {formatDate(u.last_active_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => onResetPassword(u)}
                        disabled={busyId === u.id}
                        title="寄送密碼重設信"
                        className="size-8 flex items-center justify-center rounded-md text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 disabled:opacity-40 transition-colors"
                      >
                        <KeyRound size={14} />
                      </button>
                      <button
                        onClick={() => onToggleActive(u)}
                        disabled={busyId === u.id || u.id === me?.id}
                        title={u.id === me?.id ? "不能停用自己" : u.is_active ? "停用帳號" : "啟用帳號"}
                        className={
                          u.is_active
                            ? "size-8 flex items-center justify-center rounded-md text-zinc-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-40 transition-colors"
                            : "size-8 flex items-center justify-center rounded-md text-zinc-500 hover:text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 transition-colors"
                        }
                      >
                        {u.is_active ? <UserX size={14} /> : <UserCheck size={14} />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
