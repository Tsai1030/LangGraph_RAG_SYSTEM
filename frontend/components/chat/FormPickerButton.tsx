"use client";

import { useEffect, useRef, useState } from "react";
import { Files, Download, Sparkles, ArrowLeft, AlertTriangle } from "lucide-react";
import api from "@/lib/api";
import { getAccessToken } from "@/store/authStore";
import { cn } from "@/lib/utils";
import type { FormFile } from "@/types";

interface Props {
  /** 點擊「AI 代填」時送出對話訊息。會把 popover 關掉並送出固定字串。 */
  onSendMessage: (message: string) => void;
  disabled?: boolean;
}

/**
 * FormPickerButton — InputBar 左側的表單選單觸發鈕。
 *
 * 行為：
 * - 點擊 trigger → 向上展開 popover，列出 GET /api/forms 拿到的靜態表
 * - 每張卡兩顆按鈕：
 *   - 「下載空白檔」直接呼叫 download_url 取得 .docx
 *   - 「AI 代填」先切到內嵌確認檢視；確認後送 `我要填《X》` 進對話
 * - 點外面 / Esc 關閉
 */
export default function FormPickerButton({ onSendMessage, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [forms, setForms] = useState<FormFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [confirmingForm, setConfirmingForm] = useState<FormFile | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // ── 第一次開啟時載入清單，之後快取不重抓 ───────────────
  // 注意：deps 不可包含 loading，否則 setLoading(true) 會觸發 cleanup 把 fetch 取消，
  // 造成 setLoading(false) 永遠不執行 → loading 卡在 true。
  useEffect(() => {
    if (!open || forms.length) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get<FormFile[]>("/forms");
        if (!cancelled) setForms(data);
      } catch (e) {
        if (!cancelled) setError("載入失敗，請稍後再試");
      } finally {
        // 一律重置 loading，避免「快速開關 popover 導致 cancelled=true 後卡住」
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, forms.length]);

  // ── 點外面 / Esc 關閉 ──────────────────────────────────
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        containerRef.current &&
        !containerRef.current.contains(target) &&
        triggerRef.current &&
        !triggerRef.current.contains(target)
      ) {
        closeAll();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAll();
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const closeAll = () => {
    setOpen(false);
    setConfirmingForm(null);
  };

  const handleDownload = async (form: FormFile) => {
    if (downloadingId) return;
    setDownloadingId(form.form_id);
    try {
      const token = getAccessToken();
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
      const res = await fetch(`${backendUrl}${form.download_url}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("下載失敗");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${form.display_name}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleAIFillConfirm = (form: FormFile) => {
    onSendMessage(`我要填《${form.display_name}》`);
    closeAll();
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title="選擇表單"
        aria-expanded={open}
        className={cn(
          "shrink-0 size-8 rounded-full flex items-center justify-center transition-colors",
          "hover:bg-zinc-100 active:scale-95",
          open && "bg-zinc-100",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <Files size={16} className="text-zinc-600" />
      </button>

      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 mb-2 z-50",
            "w-[min(360px,calc(100vw-2rem))]",
            "rounded-xl border border-zinc-200 bg-white shadow-lg",
            "overflow-hidden"
          )}
        >
          {/* 標題列；確認模式時切成「返回」+ 警告標題 */}
          <div className="px-4 py-3 border-b border-zinc-100 flex items-center gap-2">
            {confirmingForm ? (
              <>
                <button
                  onClick={() => setConfirmingForm(null)}
                  className="size-6 rounded hover:bg-zinc-100 flex items-center justify-center"
                  aria-label="返回"
                >
                  <ArrowLeft size={14} className="text-zinc-500" />
                </button>
                <AlertTriangle size={14} className="text-amber-500" />
                <span className="text-[12px] font-medium text-zinc-700">確認開始填寫</span>
              </>
            ) : (
              <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wide">
                選擇表單
              </span>
            )}
          </div>

          <div className="p-3">
            {confirmingForm ? (
              // ── 內嵌確認檢視 ─────────────────────────
              <div className="space-y-3">
                <p className="text-[13px] text-zinc-700 leading-relaxed">
                  將開始填寫《{confirmingForm.display_name}》。
                  <br />
                  <span className="text-zinc-500">若已有進行中填表將被取代，已填內容會清空。</span>
                </p>
                <div className="flex gap-2 justify-end pt-1">
                  <button
                    onClick={() => setConfirmingForm(null)}
                    className="px-3 h-8 rounded-lg text-[12px] font-medium text-zinc-600 hover:bg-zinc-100 transition-colors"
                  >
                    取消
                  </button>
                  <button
                    onClick={() => handleAIFillConfirm(confirmingForm)}
                    className="px-3 h-8 rounded-lg text-[12px] font-medium bg-zinc-900 text-white hover:bg-zinc-700 transition-colors flex items-center gap-1.5"
                  >
                    <Sparkles size={12} />
                    開始填寫
                  </button>
                </div>
              </div>
            ) : loading ? (
              <p className="text-[12px] text-zinc-500 text-center py-6">載入中…</p>
            ) : error ? (
              <p className="text-[12px] text-rose-500 text-center py-6">{error}</p>
            ) : (
              <ul className="space-y-2">
                {forms.map((f) => (
                  <li
                    key={f.form_id}
                    className="rounded-lg border border-zinc-200 hover:border-zinc-300 transition-colors overflow-hidden"
                  >
                    <div className="px-3 pt-2.5 pb-2 text-[13px] font-medium text-zinc-800 truncate">
                      {f.display_name}
                    </div>
                    <div className="px-2 pb-2 flex gap-1.5">
                      <button
                        onClick={() => handleDownload(f)}
                        disabled={downloadingId === f.form_id}
                        className={cn(
                          "flex-1 h-7 rounded-md text-[11px] font-medium",
                          "border border-zinc-200 bg-white text-zinc-700",
                          "hover:bg-zinc-50 hover:border-zinc-300 transition-colors",
                          "flex items-center justify-center gap-1",
                          "disabled:opacity-60 disabled:cursor-not-allowed"
                        )}
                      >
                        <Download size={11} />
                        {downloadingId === f.form_id ? "下載中…" : "下載空白檔"}
                      </button>
                      <button
                        onClick={() => setConfirmingForm(f)}
                        className={cn(
                          "flex-1 h-7 rounded-md text-[11px] font-medium",
                          "bg-zinc-900 text-white",
                          "hover:bg-zinc-700 transition-colors",
                          "flex items-center justify-center gap-1"
                        )}
                      >
                        <Sparkles size={11} />
                        AI 代填
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
