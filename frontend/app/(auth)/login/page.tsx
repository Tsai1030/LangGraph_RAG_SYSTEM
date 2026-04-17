"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/new");
    } catch {
      setError("Email 或密碼錯誤，請重試");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">歡迎回來</h1>
        <p className="text-sm text-zinc-500 mt-1">登入以繼續使用知識助理</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-700">電子信箱</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="you@company.com"
            className="h-10 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 placeholder-zinc-400 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 transition-all"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-zinc-700">密碼</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            placeholder="••••••••"
            className="h-10 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 placeholder-zinc-400 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 transition-all"
          />
        </div>

        {error && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="h-10 rounded-lg bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-400 text-white text-sm font-medium transition-colors mt-1 flex items-center justify-center gap-2"
        >
          {loading && (
            <span className="size-4 border-2 border-white/40 border-t-white rounded-full animate-spin-fast" />
          )}
          {loading ? "登入中…" : "登入"}
        </button>
      </form>

      <p className="mt-6 text-center text-xs text-zinc-400">
        沒有帳號？{" "}
        <Link href="/register" className="text-zinc-700 font-medium hover:underline underline-offset-2">
          立即註冊
        </Link>
      </p>
    </div>
  );
}
