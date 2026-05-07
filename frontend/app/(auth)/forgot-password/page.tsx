"use client";

import { useState } from "react";
import Link from "next/link";
import { forgotPassword } from "@/lib/auth";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await forgotPassword(email);
    } catch {
      // 後端永遠回 200，這裡通常不會走到
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  };

  const inputClass =
    "w-full h-11 rounded-xl border border-zinc-200 bg-zinc-50/60 px-3.5 text-sm text-zinc-900 placeholder-zinc-400 outline-none focus:bg-white focus:border-zinc-400 transition-all duration-150";

  if (submitted) {
    return (
      <div>
        <div className="mb-7">
          <h1 className="text-[1.6rem] font-bold text-zinc-900 tracking-tight leading-tight">
            請查看您的信箱
          </h1>
          <p className="text-sm text-zinc-500 mt-1.5 leading-relaxed">
            若 <span className="text-zinc-700 font-medium">{email}</span> 是已註冊的帳號，您將在數分鐘內收到一封含密碼重設連結的信件。
          </p>
          <p className="text-xs text-zinc-400 mt-3 leading-relaxed">
            連結一小時內有效。沒收到？檢查垃圾信件夾，或稍候再試一次。
          </p>
        </div>

        <Link
          href="/login"
          className="block w-full h-11 rounded-xl border border-zinc-300 bg-white text-center leading-[2.75rem] text-sm font-medium text-zinc-900 hover:bg-zinc-50 transition-colors"
        >
          返回登入
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-7">
        <h1 className="text-[1.6rem] font-bold text-zinc-900 tracking-tight leading-tight">
          忘記密碼
        </h1>
        <p className="text-sm text-zinc-400 mt-1.5">輸入您的電子信箱，我們會寄重設連結給您</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-600">電子信箱</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="you@company.com"
            className={inputClass}
          />
        </div>

        <button
          type="submit"
          disabled={loading || !email}
          className="h-11 rounded-xl bg-zinc-900 hover:bg-zinc-800 active:scale-[0.98] disabled:bg-zinc-300 text-white text-sm font-medium transition-all duration-150 mt-1 flex items-center justify-center gap-2"
        >
          {loading && (
            <span className="size-4 border-2 border-white/40 border-t-white rounded-full animate-spin-fast" />
          )}
          {loading ? "寄送中…" : "寄送重設連結"}
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
