"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { loginWithGoogle } from "@/lib/auth";
import AuthShell from "@/components/auth/AuthShell";
import GoogleSignInButton from "@/components/auth/GoogleSignInButton";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // 同一個 /auth/google endpoint 既處理登入也處理註冊：
  // 後端看 google_sub / email 是否存在，自動決定 register vs login。
  const handleCredential = async (credential: string) => {
    setError(null);
    setLoading(true);
    try {
      await loginWithGoogle(credential);
      router.replace("/new");
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      if (resp?.status === 403) {
        setError(resp.data?.detail || "僅限 @bes.com.tw 公司帳號註冊");
      } else {
        setError("註冊失敗，請稍後再試");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      pre="新員工註冊"
      tagline={<>使用公司 Google，<br />一鍵<em>加入</em>。</>}
      sub="僅限 @bes.com.tw 公司帳號 — 透過 Google 完成註冊即可立即使用。"
      index="N° 02 / Register"
    >
      <div className="auth-form__heading-block">
        <h2 className="auth-form__heading">建立<em>帳號</em>。</h2>
        <p className="auth-form__sub">請使用公司 Google 帳號註冊，系統會自動建立您的內部帳號。</p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", opacity: loading ? 0.5 : 1, pointerEvents: loading ? "none" : "auto" }}>
          <GoogleSignInButton
            text="signup_with"
            hostedDomain="bes.com.tw"
            onCredential={handleCredential}
            onError={() => setError("無法啟動 Google 註冊，請檢查網路")}
          />
        </div>

        {loading && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--auth-mute)" }}>
            <span className="auth-spinner" />
            建立帳號中…
          </div>
        )}

        {error && (
          <div className="auth-err" style={{ width: "100%" }}>
            <span className="auth-err__dot" />
            {error}
          </div>
        )}

        <p className="auth-form__caveat" style={{ marginTop: 12 }}>
          建立帳號即同意：管理員可查閱您於本系統的對話紀錄。
        </p>

        <p className="auth-form__hint">
          已有帳號？
          <Link href="/login" className="auth-meta-link auth-meta-link--strong" style={{ marginLeft: 4 }}>
            立即登入
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
