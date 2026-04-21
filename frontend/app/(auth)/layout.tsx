import Image from "next/image";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* Left panel — branding */}
      <div className="hidden lg:flex flex-col justify-between px-12 py-10 relative overflow-hidden">
        {/* 背景圖片 */}
        <Image
          src="/login_img.jpg"
          alt=""
          fill
          sizes="50vw"
          className="object-cover"
          priority
        />
        {/* 深色遮罩，確保文字可讀性 */}
        <div className="absolute inset-0 bg-zinc-950/60" />

        {/* 內容層（z-10 確保在背景圖與遮罩之上） */}
        <div className="relative z-10 flex items-center gap-3">
          <Image src="/logo.png" alt="營造知識助理" width={44} height={44} className="size-11 object-contain" />
          <span className="text-zinc-100 font-semibold text-xl">營造知識助理</span>
        </div>

        <div className="relative z-10">
          <blockquote className="text-zinc-300 text-lg font-light leading-relaxed mb-6">
            「整合 51 份營造業作業規範，<br />
            讓每位員工隨時獲得精準的知識支援。」
          </blockquote>
          <div className="flex gap-6 text-zinc-400 text-xs">
            <div><p className="text-zinc-300 font-semibold text-2xl">1,375</p><p>知識片段</p></div>
            <div><p className="text-zinc-300 font-semibold text-2xl">51</p><p>份文件</p></div>
            <div><p className="text-zinc-300 font-semibold text-2xl">RAG</p><p>智能檢索</p></div>
          </div>
        </div>

        <p className="relative z-10 text-zinc-400 text-xs">© 2026 Construction Knowledge AI</p>
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
