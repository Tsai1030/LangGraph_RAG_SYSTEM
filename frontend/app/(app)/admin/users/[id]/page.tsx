"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import api from "@/lib/api";
import type { AdminConversationOut, AdminUserOut } from "@/types/admin";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const normalized = /[Zz+]/.test(iso) ? iso : iso + "Z";
  return new Date(normalized).toLocaleString("zh-TW");
}

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id;

  const [user, setUser] = useState<AdminUserOut | null>(null);
  const [convs, setConvs] = useState<AdminConversationOut[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<AdminUserOut>(`/admin/users/${userId}`),
      api.get<AdminConversationOut[]>(`/admin/users/${userId}/conversations`),
    ])
      .then(([u, c]) => {
        if (cancelled) return;
        setUser(u.data);
        setConvs(c.data);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-zinc-500">
        <span className="size-4 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast mr-2" />
        載入中…
      </div>
    );
  }

  if (!user) {
    return <div className="text-sm text-red-600">使用者不存在</div>;
  }

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/admin/users"
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 self-start"
      >
        <ArrowLeft size={13} />
        回到使用者列表
      </Link>

      {/* User card */}
      <div className="bg-white border border-zinc-200 rounded-xl p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-zinc-900 truncate">{user.email}</h2>
              {user.role === "admin" && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-900 text-white text-xs shrink-0">
                  <ShieldCheck size={11} />
                  admin
                </span>
              )}
            </div>
            <p className="text-sm text-zinc-500 mt-1">{user.display_name ?? "（未設定名稱）"}</p>
          </div>
          <div className="text-right shrink-0">
            {user.is_active ? (
              <span className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md">
                啟用中
              </span>
            ) : (
              <span className="text-xs text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded-md">已停用</span>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-4 border-t border-zinc-100">
          <div>
            <div className="text-[11px] text-zinc-500">註冊時間</div>
            <div className="text-sm text-zinc-800 mt-0.5">{formatDate(user.created_at)}</div>
          </div>
          <div>
            <div className="text-[11px] text-zinc-500">最後活動</div>
            <div className="text-sm text-zinc-800 mt-0.5">{formatDate(user.last_active_at)}</div>
          </div>
          <div>
            <div className="text-[11px] text-zinc-500">對話總數</div>
            <div className="text-sm text-zinc-800 mt-0.5 tabular-nums">{user.conversation_count}</div>
          </div>
          <div>
            <div className="text-[11px] text-zinc-500">User ID</div>
            <div className="text-xs text-zinc-500 mt-0.5 font-mono truncate">{user.id}</div>
          </div>
        </div>
      </div>

      {/* Conversation list */}
      <section>
        <h3 className="text-sm font-medium text-zinc-700 mb-2">對話紀錄</h3>
        {convs && convs.length === 0 && (
          <div className="text-sm text-zinc-500 bg-white border border-zinc-200 rounded-xl p-6 text-center">
            此使用者尚無對話
          </div>
        )}
        {convs && convs.length > 0 && (
          <div className="bg-white border border-zinc-200 rounded-xl divide-y divide-zinc-100">
            {convs.map((c) => (
              <Link
                key={c.id}
                href={`/admin/conversations/${c.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-zinc-50 transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-zinc-900 truncate">{c.title ?? "（未命名對話）"}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">
                    {c.message_count} 則訊息 · 更新於 {formatDate(c.updated_at)}
                  </div>
                </div>
                <ArrowLeft size={14} className="text-zinc-300 rotate-180 shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
