"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", confirm: "", name: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) { setError("兩次密碼不一致"); return; }
    setLoading(true);
    try {
      await register(form.email, form.password, form.name || undefined);
      router.replace("/new");
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 429) {
        setError("嘗試太頻繁，請稍候 1 分鐘再試");
      } else {
        setError("註冊失敗，Email 可能已被使用");
      }
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
          建立帳號
        </h1>
        <p className="text-sm text-zinc-400 mt-1.5">加入公司內部知識助理系統</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        {/* Name */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">
            顯示名稱
            <span className="text-zinc-400 font-normal ml-1">（選填）</span>
          </label>
          <input
            type="text"
            value={form.name}
            onChange={set("name")}
            placeholder="王小明"
            className={inputClass}
          />
        </div>

        {/* Email */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">電子信箱</label>
          <input
            type="email"
            value={form.email}
            onChange={set("email")}
            required
            placeholder="you@company.com"
            className={inputClass}
          />
        </div>

        {/* Password */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">密碼</label>
          <div className="relative">
            <input
              type={showPwd ? "text" : "password"}
              value={form.password}
              onChange={set("password")}
              required
              placeholder="至少 8 個字元"
              minLength={8}
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

        {/* Confirm password */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">確認密碼</label>
          <div className="relative">
            <input
              type={showConfirm ? "text" : "password"}
              value={form.confirm}
              onChange={set("confirm")}
              required
              placeholder="再次輸入密碼"
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

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5">
            <span className="size-1.5 rounded-full bg-red-500 shrink-0" />
            {error}
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="h-11 rounded-xl bg-zinc-900 hover:bg-zinc-800 active:scale-[0.98] disabled:bg-zinc-300 text-white text-sm font-medium transition-all duration-150 mt-1 flex items-center justify-center gap-2"
        >
          {loading && (
            <span className="size-4 border-2 border-white/40 border-t-white rounded-full animate-spin-fast" />
          )}
          {loading ? "建立中…" : "建立帳號"}
        </button>

        {/* 隱私聲明 — admin 可查閱對話紀錄 */}
        <p className="text-[11px] leading-relaxed text-zinc-400 text-center">
          建立帳號即表示同意：為提供服務品質支援與系統管理，
          <br className="hidden sm:block" />
          管理員可能查閱您於本系統的對話紀錄。
        </p>
      </form>

      <p className="mt-6 text-center text-xs text-zinc-400">
        已有帳號？{" "}
        <Link
          href="/login"
          className="text-zinc-700 font-semibold hover:text-zinc-900 underline underline-offset-2 transition-colors"
        >
          立即登入
        </Link>
      </p>
    </div>
  );
}
