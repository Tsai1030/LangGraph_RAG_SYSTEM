import Image from "next/image";

type AuthShellProps = {
  /** 左側 pre-title 小字（mono 全大寫） */
  pre: string;
  /** 左側 display 標題（可含 React node 例如 <em> 強調） */
  tagline: React.ReactNode;
  /** 左側標題下方說明文字 */
  sub: React.ReactNode;
  /** 是否顯示左下 chips（51 份規範 / 1,375 知識片段 / RAG），預設 true */
  showChips?: boolean;
  /** 右上 N° 編號文字（mono 全大寫，例：N° 01 / Sign in） */
  index: string;
  /** 右側 form 區內容（含 heading-block + form） */
  children: React.ReactNode;
};

export default function AuthShell({
  pre,
  tagline,
  sub,
  showChips = true,
  index,
  children,
}: AuthShellProps) {
  return (
    <div className="auth-root auth-shell">
      {/* LEFT image pane */}
      <aside className="auth-pane-img">
        <div className="auth-pane-img__bg" />
        <div className="auth-pane-img__veil" />
        <div className="auth-pane-img__grain" />

        <div className="auth-pane-img__layout">
          <div className="auth-brand">
            <Image
              className="auth-brand__logo"
              src="/logo1.png"
              alt=""
              width={36}
              height={36}
              priority
            />
            <span>營造知識助理</span>
          </div>

          <div className="auth-pane-img__center">
            <div className="auth-pre">{pre}</div>
            <h1 className="auth-display">{tagline}</h1>
            <p className="auth-sub">{sub}</p>
            {showChips && (
              <div className="auth-chips">
                <span className="auth-chip"><strong>51</strong>&nbsp;份規範</span>
                <span className="auth-chip"><strong>1,375</strong>&nbsp;個知識片段</span>
                <span className="auth-chip">RAG 檢索</span>
              </div>
            )}
          </div>

          <div className="auth-pane-img__footer">
            <span>© 2026 · Construction Knowledge AI</span>
            <span>v0.4 · Internal Use</span>
          </div>
        </div>
      </aside>

      {/* RIGHT form pane */}
      <main className="auth-pane-form">
        <div className="auth-pane-form__top">
          <span className="auth-index">{index}</span>
        </div>

        <div className="auth-pane-form__center">
          {children}
        </div>

        <div className="auth-pane-form__bottom">
          <span>v0.4 · Internal · UTC+8</span>
        </div>
      </main>
    </div>
  );
}
