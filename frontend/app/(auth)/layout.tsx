import Image from "next/image";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* Left panel — branding */}
      <div className="hidden lg:flex flex-col justify-between px-12 py-10 relative overflow-hidden">
        <Image
          src="/login_img.jpg"
          alt=""
          fill
          sizes="50vw"
          className="object-cover"
          priority
        />
        {/* Gradient overlay — stronger at bottom for text legibility */}
        <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/55 via-zinc-950/50 to-zinc-950/75" />

        {/* Brand mark */}
        <div className="relative z-10 flex items-center gap-3">
          <Image
            src="/logo.png"
            alt="營造知識助理"
            width={40}
            height={40}
            className="size-10 object-contain"
          />
          <span className="text-zinc-100 font-semibold text-lg tracking-tight">營造知識助理</span>
        </div>

        {/* Quote + stats */}
        <div className="relative z-10">
          <p className="text-zinc-200 text-[1.65rem] font-light leading-snug tracking-tight mb-1">
            整合 51 份作業規範，
          </p>
          <p className="text-white text-[1.65rem] font-semibold leading-snug tracking-tight mb-10">
            讓每位員工隨時獲得精準知識支援。
          </p>

          <div className="flex gap-10">
            {[
              { num: "1,375", label: "知識片段" },
              { num: "51",    label: "份文件" },
              { num: "RAG",   label: "智能檢索" },
            ].map((s) => (
              <div key={s.label}>
                <p className="text-white text-3xl font-bold tracking-tight">{s.num}</p>
                <p className="text-zinc-400 text-xs mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 text-zinc-500 text-xs">© 2026 Construction Knowledge AI</p>
      </div>

      {/* Right panel — form */}
      <div className="flex flex-col bg-dot-grid">
        {/* Mobile logo — only shown when left panel is hidden */}
        <div className="lg:hidden flex items-center gap-2.5 px-6 pt-8 pb-2">
          <Image src="/logo.png" alt="" width={28} height={28} className="size-7 object-contain" />
          <span className="text-zinc-800 font-semibold text-sm tracking-tight">營造知識助理</span>
        </div>

        <div className="flex-1 flex items-center justify-center px-6 py-12">
          <div className="w-full max-w-sm bg-white rounded-3xl border border-zinc-200 shadow-sm px-8 py-9">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
