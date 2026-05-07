"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, EyeOff } from "lucide-react";
import api from "@/lib/api";
import type { AdminConversationDetail } from "@/types/admin";
import { cn } from "@/lib/utils";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const normalized = /[Zz+]/.test(iso) ? iso : iso + "Z";
  return new Date(normalized).toLocaleString("zh-TW");
}

export default function AdminConversationViewerPage() {
  const params = useParams<{ id: string }>();
  const convId = params.id;

  const [conv, setConv] = useState<AdminConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminConversationDetail>(`/admin/conversations/${convId}`)
      .then(({ data }) => setConv(data))
      .catch(() => setError("無法載入對話"))
      .finally(() => setLoading(false));
  }, [convId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-zinc-500">
        <span className="size-4 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast mr-2" />
        載入中…
      </div>
    );
  }

  if (error || !conv) {
    return <div className="text-sm text-red-600">{error ?? "對話不存在"}</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Privacy notice */}
      <div className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        <EyeOff size={13} className="text-amber-700 shrink-0 mt-[1px]" />
        <span>
          您正以管理員身分檢視他人對話。此操作可能受審計記錄。請勿將內容轉述或外傳。
        </span>
      </div>

      <div className="flex items-center gap-2">
        {conv.user_id ? (
          <Link
            href={`/admin/users/${conv.user_id}`}
            className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900"
          >
            <ArrowLeft size={13} />
            回到使用者
          </Link>
        ) : (
          <Link href="/admin/users" className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900">
            <ArrowLeft size={13} />
            回到使用者列表
          </Link>
        )}
      </div>

      {/* Conv header */}
      <div className="bg-white border border-zinc-200 rounded-xl p-5">
        <h2 className="text-lg font-semibold text-zinc-900 break-words">
          {conv.title ?? "（未命名對話）"}
        </h2>
        <div className="text-xs text-zinc-500 mt-1">
          所有人：{conv.user_email ?? conv.user_id} · 共 {conv.message_count} 則 · 建立 {formatDate(conv.created_at)}
        </div>
      </div>

      {/* Messages */}
      <div className="flex flex-col gap-3">
        {conv.messages.length === 0 && (
          <div className="text-sm text-zinc-500 bg-white border border-zinc-200 rounded-xl p-6 text-center">
            此對話尚無訊息
          </div>
        )}
        {conv.messages.map((m) => {
          const isUser = m.role === "user";
          const isSystem = m.role === "system";
          return (
            <div
              key={m.id}
              className={cn(
                "rounded-xl border p-4",
                isUser && "bg-zinc-900 border-zinc-900 text-zinc-100",
                !isUser && !isSystem && "bg-white border-zinc-200 text-zinc-900",
                isSystem && "bg-zinc-50 border-zinc-200 text-zinc-600"
              )}
            >
              <div
                className={cn(
                  "text-[11px] uppercase tracking-wide mb-1.5",
                  isUser ? "text-zinc-400" : "text-zinc-400"
                )}
              >
                {m.role}
                <span className="ml-2 text-zinc-400/80 normal-case tracking-normal">
                  {formatDate(m.created_at)}
                </span>
                {m.token_count != null && (
                  <span className="ml-2 text-zinc-400/80 normal-case tracking-normal">
                    · {m.token_count} tokens
                  </span>
                )}
              </div>
              <div className="text-sm whitespace-pre-wrap break-words leading-relaxed">{m.content}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
