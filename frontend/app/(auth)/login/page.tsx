"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { login } from "@/lib/auth";
import AuthShell from "@/components/auth/AuthShell";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/new");
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 429) {
        setError("嘗試太頻繁，請稍候 1 分鐘再試");
      } else if (status === 403) {
        setError("此帳號已停用，請聯絡管理員");
      } else {
        setError("Email 或密碼錯誤，請重試");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      pre="Internal Knowledge AI"
      tagline={<>把每一份規範，<br />變成可以<em>對話</em>的知識。</>}
      sub="公司內部 RAG 知識助理 — 規範、流程、表單作業，都在對話裡完成。"
      index="N° 01 / Sign in"
    >
      <div className="auth-form__heading-block">
        <h2 className="auth-form__heading">歡迎<em>回來</em>。</h2>
        <p className="auth-form__sub">請使用公司信箱登入。</p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="auth-field">
          <label className="auth-field-label">電子信箱</label>
          <input
            className="auth-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="you@company.com"
          />
        </div>

        <div className="auth-field">
          <label className="auth-field-label">密碼</label>
          <div className="auth-pwd-wrap">
            <input
              className="auth-input auth-input--with-eye"
              type={showPwd ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="••••••••"
            />
            <button
              type="button"
              className="auth-pwd-eye"
              onClick={() => setShowPwd((v) => !v)}
              aria-label={showPwd ? "隱藏密碼" : "顯示密碼"}
              tabIndex={-1}
            >
              {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 2, fontSize: 11.5 }}>
            <Link href="/forgot-password" className="auth-meta-link">
              忘記密碼？
            </Link>
          </div>
        </div>

        {error && (
          <div className="auth-err">
            <span className="auth-err__dot" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="auth-btn-ink"
          style={{ marginTop: 4 }}
        >
          {loading && <span className="auth-spinner" />}
          {loading ? "登入中…" : <>登入 <span className="auth-btn-ink__arrow">→</span></>}
        </button>

        <p className="auth-form__hint">
          沒有帳號？
          <Link href="/register" className="auth-meta-link auth-meta-link--strong" style={{ marginLeft: 4 }}>
            立即註冊
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
