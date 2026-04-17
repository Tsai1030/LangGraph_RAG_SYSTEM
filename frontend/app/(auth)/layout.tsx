export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* Left panel — branding */}
      <div className="hidden lg:flex flex-col justify-between bg-zinc-950 px-12 py-10">
        <div className="flex items-center gap-2.5">
          <div className="size-7 rounded-md bg-white flex items-center justify-center">
            <span className="text-[11px] font-bold text-zinc-900 tracking-tight">AI</span>
          </div>
          <span className="text-zinc-100 font-medium text-sm">營造知識助理</span>
        </div>

        <div>
          <blockquote className="text-zinc-300 text-lg font-light leading-relaxed mb-6">
            「整合 51 份營造業作業規範，<br />
            讓每位員工隨時獲得精準的知識支援。」
          </blockquote>
          <div className="flex gap-6 text-zinc-600 text-xs">
            <div><p className="text-zinc-300 font-semibold text-2xl">1,375</p><p>知識片段</p></div>
            <div><p className="text-zinc-300 font-semibold text-2xl">51</p><p>份文件</p></div>
            <div><p className="text-zinc-300 font-semibold text-2xl">RAG</p><p>智能檢索</p></div>
          </div>
        </div>

        <p className="text-zinc-700 text-xs">© 2026 Construction Knowledge AI</p>
      </div>

      {/* Right panel — form */}
      <div className="flex items-center justify-center px-6 py-12 bg-zinc-50">
        <div className="w-full max-w-sm">
          {children}
        </div>
      </div>
    </div>
  );
}
