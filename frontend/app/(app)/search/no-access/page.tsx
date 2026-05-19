"use client";

import { useRouter } from "next/navigation";
import { ShieldAlert, ArrowLeft } from "lucide-react";

/**
 * Fallback shown when a logged-in user without search_enabled lands on
 * any /search/* page. Layout's guard bounces them here; this page MUST
 * NOT redirect (the loop check in layout already exempts it, but
 * defence in depth — don't add a router.replace here).
 *
 * Single CTA back to /new. We deliberately don't expose admin email
 * here — admin contact info should come from a separate config, not
 * hardcoded in a frontend page.
 */
export default function SearchNoAccessPage() {
  const router = useRouter();
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="max-w-md text-center">
        <div className="inline-flex items-center justify-center size-14 rounded-full bg-zinc-100 mb-5">
          <ShieldAlert className="size-7 text-zinc-500" />
        </div>
        <h1 className="text-xl font-semibold text-zinc-900">
          鋼筋盤價助理尚未開通
        </h1>
        <p className="mt-3 text-sm text-zinc-600 leading-relaxed">
          此功能需要管理員授權後才能使用。請聯絡系統管理員 pijh102511@gmail.com，告知您的帳號 email，
          授權後重新整理本頁即可進入。
        </p>
        <button
          onClick={() => router.push("/new")}
          className="mt-6 inline-flex items-center gap-2 px-4 h-9 rounded-lg border border-zinc-300 bg-white text-sm text-zinc-900 hover:bg-zinc-50 transition-colors"
        >
          <ArrowLeft className="size-4" />
          返回對話
        </button>
      </div>
    </div>
  );
}
