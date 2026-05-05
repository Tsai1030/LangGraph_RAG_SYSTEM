"use client";

import { useEffect, useRef, useState } from "react";
import {
  Files,
  Download,
  Sparkles,
  ArrowLeft,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
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
 * - 每列：表單名 + 右側 chevron。hover 整列彈出右側子選單（Download / Ask AI）
 *   - hover 子選單只會在游標停留時顯示
 *   - 點擊整列會把該列的子選單鎖定，再點同列或別列才會切換
 * - 點「Ask AI」走現有確認檢視；點「Download」直接下載 docx
 * - 點外面 / Esc 關閉
 */
export default function FormPickerButton({ onSendMessage, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [forms, setForms] = useState<FormFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [confirmingForm, setConfirmingForm] = useState<FormFile | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [lockedId, setLockedId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // ── 第一次開啟時載入清單，之後快取不重抓 ───────────────
  useEffect(() => {
    if (!open || forms.length) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get<FormFile[]>("/forms");
        if (!cancelled) setForms(data);
      } catch {
        if (!cancelled) setError("載入失敗，請稍後再試");
      } finally {
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
    setHoveredId(null);
    setLockedId(null);
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

  const activeId = lockedId ?? hoveredId;

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
            "w-[260px]",
            "rounded-xl border border-zinc-200 bg-white shadow-lg"
          )}
        >
          {/* 標題列；確認模式時切成「返回」+ 警告標題 */}
          <div className="px-4 py-3 flex items-center gap-2">
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

          <div className="px-2 pb-2">
            {confirmingForm ? (
              // ── 內嵌確認檢視 ─────────────────────────
              <div className="px-2 space-y-3">
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
                    Cancel
                  </button>
                  <button
                    onClick={() => handleAIFillConfirm(confirmingForm)}
                    className="px-3 h-8 rounded-lg text-[12px] font-medium text-zinc-600 hover:bg-zinc-100 transition-colors"
                  >
                    Start
                  </button>
                </div>
              </div>
            ) : loading ? (
              <p className="text-[12px] text-zinc-500 text-center py-6">載入中…</p>
            ) : error ? (
              <p className="text-[12px] text-rose-500 text-center py-6">{error}</p>
            ) : (
              <ul onMouseLeave={() => setHoveredId(null)}>
                {forms.map((f) => {
                  const isActive = activeId === f.form_id;
                  return (
                    <li
                      key={f.form_id}
                      className="relative"
                      onMouseEnter={() => setHoveredId(f.form_id)}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setLockedId((prev) => (prev === f.form_id ? null : f.form_id))
                        }
                        className={cn(
                          "w-full flex items-center gap-2 px-3 py-2 rounded-lg",
                          "text-left text-[14px] text-zinc-800 transition-colors",
                          isActive && "bg-zinc-100"
                        )}
                      >
                        <span className="flex-1 truncate">{f.display_name}</span>
                        <ChevronRight size={14} className="shrink-0 text-zinc-400" />
                      </button>

                      {isActive && (
                        <div
                          className={cn(
                            "absolute left-full top-0 ml-1 z-10",
                            "w-40 rounded-lg border border-zinc-200 bg-white shadow-lg",
                            "p-1"
                          )}
                        >
                          <button
                            onClick={() => handleDownload(f)}
                            disabled={downloadingId === f.form_id}
                            className={cn(
                              "w-full flex items-center gap-2 px-2 py-2 rounded-md",
                              "text-[13px] text-zinc-700 hover:bg-zinc-100 transition-colors",
                              "disabled:opacity-60 disabled:cursor-not-allowed"
                            )}
                          >
                            <Download size={13} className="text-zinc-500" />
                            {downloadingId === f.form_id ? "Downloading…" : "Download"}
                          </button>
                          <button
                            onClick={() => setConfirmingForm(f)}
                            className={cn(
                              "w-full flex items-center gap-2 px-2 py-2 rounded-md",
                              "text-[13px] text-zinc-700 hover:bg-zinc-100 transition-colors"
                            )}
                          >
                            <Sparkles size={13} className="text-zinc-500" />
                            Ask AI
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
