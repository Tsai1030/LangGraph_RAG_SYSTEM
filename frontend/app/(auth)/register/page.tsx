"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", confirm: "", name: "" });
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
    } catch {
      setError("註冊失敗，Email 可能已被使用");
    } finally {
      setLoading(false);
    }
  };

  const fields = [
    { key: "name" as const, label: "顯示名稱", type: "text", placeholder: "王小明", optional: true },
    { key: "email" as const, label: "電子信箱", type: "email", placeholder: "you@company.com" },
    { key: "password" as const, label: "密碼", type: "password", placeholder: "至少 8 個字元", minLength: 8 },
    { key: "confirm" as const, label: "確認密碼", type: "password", placeholder: "再次輸入密碼" },
  ];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">建立帳號</h1>
        <p className="text-sm text-zinc-500 mt-1">加入公司內部知識助理系統</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        {fields.map(({ key, label, type, placeholder, optional, minLength }) => (
          <div key={key} className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-zinc-700">
              {label}
              {optional && <span className="text-zinc-400 font-normal ml-1">（選填）</span>}
            </label>
            <input
              type={type}
              value={form[key]}
              onChange={set(key)}
              required={!optional}
              placeholder={placeholder}
              minLength={minLength}
              className="h-10 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 placeholder-zinc-400 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 transition-all"
            />
          </div>
        ))}

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
          {loading ? "建立中…" : "建立帳號"}
        </button>
      </form>

      <p className="mt-6 text-center text-xs text-zinc-400">
        已有帳號？{" "}
        <Link href="/login" className="text-zinc-700 font-medium hover:underline underline-offset-2">
          立即登入
        </Link>
      </p>
    </div>
  );
}
