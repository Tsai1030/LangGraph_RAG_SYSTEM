"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { register } from "@/lib/auth";
import AuthShell from "@/components/auth/AuthShell";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", confirm: "", name: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) {
      setError("兩次密碼不一致");
      return;
    }
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

  return (
    <AuthShell
      pre="新員工註冊"
      tagline={<>建立帳號，<br />加入內部<em>知識網絡</em>。</>}
      sub="建立帳號後即可使用 RAG 智能檢索與動態表單生成功能。"
      index="N° 02 / Register"
    >
      <div className="auth-form__heading-block">
        <h2 className="auth-form__heading">建立<em>帳號</em>。</h2>
        <p className="auth-form__sub">使用公司信箱建立內部使用帳號。</p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="auth-field">
          <label className="auth-field-label">
            顯示名稱<span className="auth-field-label__opt">（選填）</span>
          </label>
          <input
            className="auth-input"
            type="text"
            value={form.name}
            onChange={set("name")}
            placeholder="王小明"
          />
        </div>

        <div className="auth-field">
          <label className="auth-field-label">電子信箱</label>
          <input
            className="auth-input"
            type="email"
            value={form.email}
            onChange={set("email")}
            required
            placeholder="you@company.com"
          />
        </div>

        <div className="auth-field">
          <label className="auth-field-label">
            密碼<span className="auth-field-label__opt">（至少 8 字元）</span>
          </label>
          <div className="auth-pwd-wrap">
            <input
              className="auth-input auth-input--with-eye"
              type={showPwd ? "text" : "password"}
              value={form.password}
              onChange={set("password")}
              required
              minLength={8}
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
        </div>

        <div className="auth-field">
          <label className="auth-field-label">確認密碼</label>
          <input
            className="auth-input"
            type={showPwd ? "text" : "password"}
            value={form.confirm}
            onChange={set("confirm")}
            required
            placeholder="再次輸入"
          />
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
          {loading ? "建立中…" : <>建立帳號 <span className="auth-btn-ink__arrow">→</span></>}
        </button>

        <p className="auth-form__caveat">
          建立帳號即同意：管理員可查閱您於本系統的對話紀錄。
        </p>

        <p className="auth-form__hint">
          已有帳號？
          <Link href="/login" className="auth-meta-link auth-meta-link--strong" style={{ marginLeft: 4 }}>
            立即登入
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}
