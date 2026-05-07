"use client";

import { useState } from "react";
import Link from "next/link";
import { forgotPassword } from "@/lib/auth";
import AuthShell from "@/components/auth/AuthShell";

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

  return (
    <AuthShell
      pre="密碼重設"
      tagline={<>沒事，<br />我們<em>協助您</em>重設。</>}
      sub="輸入公司信箱，我們會寄送一封含重設連結的信件。"
      index="N° 03 / Recover"
    >
      {submitted ? (
        <>
          <div className="auth-form__heading-block">
            <h2 className="auth-form__heading">請<em>查看信箱</em>。</h2>
            <p className="auth-form__sub" style={{ marginTop: 4 }}>
              若 <span style={{ color: "var(--auth-ink)", fontWeight: 500 }}>{email}</span>{" "}
              是已註冊的帳號，您將在數分鐘內收到一封含密碼重設連結的信件。
            </p>
            <p className="auth-form__caveat" style={{ textAlign: "left", marginTop: 8 }}>
              連結一小時內有效。沒收到請檢查垃圾信件夾。
            </p>
          </div>
          <Link
            href="/login"
            className="auth-btn-ink"
            style={{
              marginTop: 4,
              background: "white",
              color: "var(--auth-ink)",
              border: "1px solid var(--auth-line)",
              textDecoration: "none",
            }}
          >
            返回登入
          </Link>
        </>
      ) : (
        <>
          <div className="auth-form__heading-block">
            <h2 className="auth-form__heading">重設<em>密碼</em>。</h2>
            <p className="auth-form__sub">輸入信箱，我們會寄重設連結給您。</p>
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

            <button
              type="submit"
              disabled={loading || !email}
              className="auth-btn-ink"
              style={{ marginTop: 4 }}
            >
              {loading && <span className="auth-spinner" />}
              {loading ? "寄送中…" : <>寄送重設連結 <span className="auth-btn-ink__arrow">→</span></>}
            </button>

            <p className="auth-form__caveat">
              連結一小時內有效。沒收到請檢查垃圾信件夾。
            </p>

            <p className="auth-form__hint">
              想起密碼了？
              <Link href="/login" className="auth-meta-link auth-meta-link--strong" style={{ marginLeft: 4 }}>
                返回登入
              </Link>
            </p>
          </form>
        </>
      )}
    </AuthShell>
  );
}
