"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { resetPassword } from "@/lib/auth";
import AuthShell from "@/components/auth/AuthShell";

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <AuthShell
          pre="設定新密碼"
          tagline={<>設定<em>新密碼</em>，<br />立即繼續使用。</>}
          sub="設定一個新密碼，至少 8 個字元。設定後立即登入。"
          index="N° 04 / Reset"
        >
          <p className="auth-form__sub">載入中…</p>
        </AuthShell>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
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

  return (
    <AuthShell
      pre="設定新密碼"
      tagline={<>設定<em>新密碼</em>，<br />立即繼續使用。</>}
      sub="設定一個新密碼，至少 8 個字元。設定後立即登入。"
      index="N° 04 / Reset"
    >
      <div className="auth-form__heading-block">
        <h2 className="auth-form__heading">設定<em>新密碼</em>。</h2>
        <p className="auth-form__sub">設定一組新密碼以登入系統。</p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="auth-field">
          <label className="auth-field-label">
            新密碼<span className="auth-field-label__opt">（至少 8 字元）</span>
          </label>
          <div className="auth-pwd-wrap">
            <input
              className="auth-input auth-input--with-eye"
              type={showPwd ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder="輸入新密碼"
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
        </div>

        <div className="auth-field">
          <label className="auth-field-label">確認新密碼</label>
          <div className="auth-pwd-wrap">
            <input
              className="auth-input auth-input--with-eye"
              type={showConfirm ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={8}
              placeholder="再次輸入新密碼"
            />
            <button
              type="button"
              className="auth-pwd-eye"
              onClick={() => setShowConfirm((v) => !v)}
              aria-label={showConfirm ? "隱藏密碼" : "顯示密碼"}
              tabIndex={-1}
            >
              {showConfirm ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
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
          disabled={loading || !token}
          className="auth-btn-ink"
          style={{ marginTop: 4 }}
        >
          {loading && <span className="auth-spinner" />}
          {loading ? "重設中…" : <>重設並登入 <span className="auth-btn-ink__arrow">→</span></>}
        </button>

        <p className="auth-form__hint">
          想起密碼了？
          <Link href="/login" className="auth-meta-link auth-meta-link--strong" style={{ marginLeft: 4 }}>
            返回登入
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
