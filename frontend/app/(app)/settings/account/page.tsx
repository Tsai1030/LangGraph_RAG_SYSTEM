"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Link2, Unlink, AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { linkGoogle, unlinkGoogle } from "@/lib/auth";
import { useAuthStore } from "@/store/authStore";
import GoogleSignInButton from "@/components/auth/GoogleSignInButton";
import type { User } from "@/types";

export default function AccountSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // 第一次進來 user 可能還沒 ready（從 store 為空），主動 fetch 一次
  useEffect(() => {
    if (!user) {
      api.get<User>("/auth/me").then(({ data }) => setUser(data)).catch(() => {});
    }
  }, [user, setUser]);

  const refreshMe = async () => {
    const { data } = await api.get<User>("/auth/me");
    setUser(data);
  };

  const handleLink = async (credential: string) => {
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      await linkGoogle(credential);
      await refreshMe();
      setSuccess("已成功綁定 Google 帳號");
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      setError(resp?.data?.detail || "綁定失敗，請稍後再試");
    } finally {
      setLoading(false);
    }
  };

  const handleUnlink = async () => {
    if (!confirm("確定要解除 Google 綁定？解除後將只能用密碼登入。")) return;
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      await unlinkGoogle();
      await refreshMe();
      setSuccess("已解除 Google 綁定");
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      setError(resp?.data?.detail || "解除失敗");
    } finally {
      setLoading(false);
    }
  };

  if (!user) {
    return (
      <div className="p-8 text-sm text-zinc-500">載入中…</div>
    );
  }

  return (
    <div className="p-6 md:p-10 max-w-2xl mx-auto w-full">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-zinc-900">帳號設定</h1>
        <p className="mt-1 text-sm text-zinc-500">管理您的登入方式與帳號綁定。</p>
      </header>

      {/* 基本資訊 */}
      <section className="mb-6 bg-white border border-zinc-200 rounded-xl p-5">
        <h2 className="text-sm font-medium text-zinc-900 mb-3">基本資訊</h2>
        <dl className="text-sm space-y-2">
          <div className="flex justify-between">
            <dt className="text-zinc-500">電子信箱</dt>
            <dd className="text-zinc-900 font-mono">{user.email}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-zinc-500">顯示名稱</dt>
            <dd className="text-zinc-900">{user.display_name || "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-zinc-500">角色</dt>
            <dd className="text-zinc-900">{user.role === "admin" ? "管理員" : "一般使用者"}</dd>
          </div>
        </dl>
      </section>

      {/* Google 綁定 */}
      <section className="mb-6 bg-white border border-zinc-200 rounded-xl p-5">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-sm font-medium text-zinc-900">Google 綁定</h2>
            <p className="mt-1 text-xs text-zinc-500">
              綁定後可使用 Google 一鍵登入。只能綁定與本帳號相同 email 的公司 Google 帳號。
            </p>
          </div>
          {user.google_linked ? (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              <CheckCircle2 size={12} /> 已綁定
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-zinc-100 text-zinc-600 border border-zinc-200">
              未綁定
            </span>
          )}
        </div>

        {user.google_linked ? (
          <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-100">
            <span className="text-sm text-zinc-700">已啟用 Google 登入</span>
            <button
              onClick={handleUnlink}
              disabled={loading || !user.has_password}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-zinc-200 text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 disabled:cursor-not-allowed"
              title={!user.has_password ? "您的帳號沒有密碼，無法解除綁定" : ""}
            >
              <Unlink size={12} />
              解除綁定
            </button>
          </div>
        ) : (
          <div className="mt-4 pt-4 border-t border-zinc-100">
            <div className="flex items-center gap-2 text-xs text-zinc-500 mb-3">
              <Link2 size={12} />
              點下方按鈕，使用 <span className="font-mono">{user.email}</span> 的 Google 登入即可綁定
            </div>
            <div style={{ opacity: loading ? 0.5 : 1, pointerEvents: loading ? "none" : "auto" }}>
              <GoogleSignInButton
                text="continue_with"
                hostedDomain="bes.com.tw"
                onCredential={handleLink}
                onError={() => setError("無法啟動 Google，請檢查網路")}
              />
            </div>
          </div>
        )}

        {!user.has_password && user.google_linked && (
          <div className="mt-4 text-xs text-zinc-500 flex items-start gap-1.5">
            <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
            您的帳號沒有設定密碼（純 Google 帳號），無法解除綁定 — 否則將無法登入。
          </div>
        )}
      </section>

      {/* 訊息 */}
      {error && (
        <div className="mb-4 p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
          {error}
        </div>
      )}
      {success && (
        <div className="mb-4 p-3 rounded-md bg-emerald-50 border border-emerald-200 text-sm text-emerald-700 flex items-start gap-2">
          <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0" />
          {success}
        </div>
      )}
    </div>
  );
}
