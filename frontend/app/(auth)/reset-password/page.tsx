"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { resetPassword } from "@/lib/auth";

export default function ResetPasswordPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const t = params.get("token");
    setToken(t);
    if (!t) setError("連結無效或已過期");
  }, [params]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!token) return;
    if (password.length < 8) {
      setError("密碼至少 8 個字元");
      return;
    }
    if (password !== confirm) {
      setError("兩次密碼不一致");
      return;
    }
    setLoading(true);
    try {
      await resetPassword(token, password);
      router.replace("/new");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? null;
      setError(detail || "重設失敗，連結可能已失效");
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full h-11 rounded-xl border border-zinc-200 bg-zinc-50/60 px-3.5 text-sm text-zinc-900 placeholder-zinc-400 outline-none focus:bg-white focus:border-zinc-400 transition-all duration-150";

  return (
    <div>
      <div className="mb-7">
        <h1 className="text-[1.6rem] font-bold text-zinc-900 tracking-tight leading-tight">
          重設密碼
        </h1>
        <p className="text-sm text-zinc-400 mt-1.5">設定一個新的密碼以登入</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {/* New password */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">新密碼</label>
          <div className="relative">
            <input
              type={showPwd ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder="至少 8 個字元"
              className={`${inputClass} pr-10`}
            />
            <button
              type="button"
              onClick={() => setShowPwd((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 transition-colors"
              tabIndex={-1}
            >
              {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
        </div>

        {/* Confirm */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">確認新密碼</label>
          <div className="relative">
            <input
              type={showConfirm ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={8}
              placeholder="再次輸入新密碼"
              className={`${inputClass} pr-10`}
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 transition-colors"
              tabIndex={-1}
            >
              {showConfirm ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5">
            <span className="size-1.5 rounded-full bg-red-500 shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !token}
          className="h-11 rounded-xl bg-zinc-900 hover:bg-zinc-800 active:scale-[0.98] disabled:bg-zinc-300 text-white text-sm font-medium transition-all duration-150 mt-1 flex items-center justify-center gap-2"
        >
          {loading && (
            <span className="size-4 border-2 border-white/40 border-t-white rounded-full animate-spin-fast" />
          )}
          {loading ? "重設中…" : "重設並登入"}
        </button>
      </form>

      <p className="mt-6 text-center text-xs text-zinc-400">
        想起密碼了？{" "}
        <Link
          href="/login"
          className="text-zinc-700 font-semibold hover:text-zinc-900 underline underline-offset-2 transition-colors"
        >
          返回登入
        </Link>
      </p>
    </div>
  );
}
