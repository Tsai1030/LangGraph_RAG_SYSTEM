"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { HardHat, Mail, Lock, User, ArrowRight, AlertCircle } from "lucide-react";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("兩次輸入的密碼不一致");
      return;
    }
    setLoading(true);
    try {
      await register(email, password, displayName || undefined);
      router.replace("/new");
    } catch {
      setError("註冊失敗，請確認 Email 是否已被使用");
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full bg-white/10 border border-white/20 rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/50 transition-colors";

  return (
    <div className="bg-white/5 backdrop-blur-md rounded-2xl border border-white/10 shadow-2xl p-8">
      {/* Logo */}
      <div className="flex flex-col items-center mb-7">
        <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center mb-3 shadow-lg">
          <HardHat size={24} className="text-white" />
        </div>
        <h1 className="text-xl font-bold text-white">建立帳號</h1>
        <p className="text-slate-400 text-sm mt-0.5">加入營造知識助理</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3.5">
        {/* Display Name */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            顯示名稱 <span className="text-slate-500">（選填）</span>
          </label>
          <div className="relative">
            <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="王小明"
              className={inputClass}
            />
          </div>
        </div>

        {/* Email */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">Email</label>
          <div className="relative">
            <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="your@email.com"
              className={inputClass}
            />
          </div>
        </div>

        {/* Password */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            密碼 <span className="text-slate-500">（至少 8 字元）</span>
          </label>
          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder="••••••••"
              className={inputClass}
            />
          </div>
        </div>

        {/* Confirm Password */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">確認密碼</label>
          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              placeholder="••••••••"
              className={inputClass}
            />
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
            <AlertCircle size={14} className="text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50 text-white font-medium rounded-xl py-2.5 text-sm transition-all mt-1"
        >
          {loading ? (
            <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin-custom" />
          ) : (
            <>
              建立帳號
              <ArrowRight size={15} />
            </>
          )}
        </button>
      </form>

      <p className="mt-5 text-sm text-center text-slate-500">
        已有帳號？{" "}
        <Link href="/login" className="text-blue-400 hover:text-blue-300 transition-colors">
          立即登入
        </Link>
      </p>
    </div>
  );
}
