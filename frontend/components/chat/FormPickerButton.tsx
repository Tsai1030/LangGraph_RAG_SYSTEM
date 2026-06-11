"use client";

import { type ChangeEvent, useEffect, useRef, useState } from "react";
import {
  Plus,
  Files,
  ImagePlus,
  Paperclip,
  Download,
  Sparkles,
  ArrowLeft,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import api from "@/lib/api";
import { getAccessToken } from "@/store/authStore";
import { cn } from "@/lib/utils";
import type { FormFile, PendingDocument, PendingImage } from "@/types";

interface Props {
  /** 點擊「AI 代填」時送出對話訊息。會把 popover 關掉並送出固定字串。 */
  onSendMessage: (message: string) => void;
  /** 上傳圖片成功後回傳給 InputBar 暫存（送出時帶 image_id）。未提供時不顯示「上傳圖片」、直接開到表單清單。 */
  onAddImage?: (img: PendingImage) => void;
  /** 文件上傳（PDF/DOCX/PPTX）三段式回呼：選檔當下先以暫時 id 顯示載入卡，
   *  完成後以後端 document_id 取代，失敗則移除卡片並顯示錯誤。
   *  文件索引綁對話，需同時提供 getConversationId 才顯示「上傳文件」。
   *  /new 頁可在 getConversationId 內先建立對話再回傳 id（lazy create）。 */
  onDocumentUploadStart?: (doc: PendingDocument) => void;
  onDocumentUploadDone?: (tempId: string, doc: PendingDocument) => void;
  onDocumentUploadError?: (tempId: string, message: string) => void;
  getConversationId?: () => Promise<string>;
  disabled?: boolean;
}

/**
 * FormPickerButton — InputBar 左側的「+」新增選單觸發鈕。
 *
 * 點「+」展開 root 選單（樣式與原表單選單一致）：
 *   - 選擇表單 → 進入表單清單（GET /api/forms；每列 hover 子選單 Download / Ask AI）
 *   - 上傳圖片 → 開檔案選擇器，上傳到 /api/chat/upload，回傳 image_id 給 InputBar
 * 點外面 / Esc 關閉。
 */
export default function FormPickerButton({
  onSendMessage,
  onAddImage,
  onDocumentUploadStart,
  onDocumentUploadDone,
  onDocumentUploadError,
  getConversationId,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"root" | "forms">("root");
  const [forms, setForms] = useState<FormFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [confirmingForm, setConfirmingForm] = useState<FormFile | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [lockedId, setLockedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const docInputRef = useRef<HTMLInputElement>(null);

  const canUploadDocument = Boolean(onDocumentUploadStart && getConversationId);

  // ── 進入表單清單時載入清單，之後快取不重抓 ─────────────
  useEffect(() => {
    if (view !== "forms" || forms.length) return;
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
  }, [view, forms.length]);

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
    setView("root");
    setConfirmingForm(null);
    setHoveredId(null);
    setLockedId(null);
    setUploadError(null);
  };

  const toggleOpen = () => {
    if (open) {
      closeAll();
    } else {
      // 有 onAddImage（聊天 InputBar）→ 開 root 兩層選單；否則（新對話頁）直接開表單清單
      setView(onAddImage ? "root" : "forms");
      setUploadError(null);
      setOpen(true);
    }
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

  // ── 上傳文件 → /api/chat/upload-document（後端同步解析+索引，較耗時）──
  // 選檔當下即關閉 popover、在 InputBar 顯示 skeleton 載入卡；完成/失敗再回報
  const handleDocChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length || !getConversationId) return;

    const entries = files.map((file) => ({
      file,
      tempId: `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    }));
    entries.forEach(({ file, tempId }) =>
      onDocumentUploadStart?.({
        document_id: tempId,
        filename: file.name,
        size: file.size,
        status: "uploading",
      })
    );
    closeAll();

    let conversationId: string;
    try {
      // /new 頁此 callback 會先建立對話再回傳 id（索引必須綁對話）
      conversationId = await getConversationId();
    } catch {
      entries.forEach(({ tempId }) =>
        onDocumentUploadError?.(tempId, "建立對話失敗，請稍後再試")
      );
      return;
    }

    for (const { file, tempId } of entries) {
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("conversation_id", conversationId);
        const { data } = await api.post<{
          document_id: string;
          filename: string;
          chunk_count: number;
        }>("/chat/upload-document", fd);
        onDocumentUploadDone?.(tempId, {
          document_id: data.document_id,
          filename: data.filename,
          size: file.size,
          status: "ready",
        });
      } catch (err: unknown) {
        // 後端 400 帶有明確訊息（格式不符 / 掃描檔無文字等），直接顯示
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        onDocumentUploadError?.(tempId, detail ?? "上傳失敗，請稍後再試");
      }
    }
  };

  // ── 上傳圖片 → /api/chat/upload，回傳 image_id 給 InputBar ──
  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // 清空 input，讓同一張圖可重選
    if (!files.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        const { data } = await api.post<{ image_id: string; mime_type: string }>(
          "/chat/upload",
          fd
        );
        onAddImage?.({
          image_id: data.image_id,
          mime_type: data.mime_type,
          preview_url: URL.createObjectURL(file),
          name: file.name,
        });
      }
      closeAll();
    } catch {
      setUploadError("上傳失敗，請稍後再試");
    } finally {
      setUploading(false);
    }
  };

  const activeId = lockedId ?? hoveredId;

  return (
    <div className="relative" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={toggleOpen}
        disabled={disabled}
        title="新增"
        aria-expanded={open}
        className={cn(
          "shrink-0 size-8 rounded-full flex items-center justify-center transition-colors",
          "hover:bg-zinc-100 active:scale-95",
          open && "bg-zinc-100",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <Plus size={18} className="text-zinc-600" />
      </button>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        hidden
        onChange={handleFileChange}
      />

      <input
        ref={docInputRef}
        type="file"
        accept=".pdf,.docx,.pptx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        hidden
        onChange={handleDocChange}
      />

      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 mb-2 z-50",
            "w-[260px]",
            "rounded-xl border border-zinc-200 bg-white shadow-lg"
          )}
        >
          {/* 標題列：root / 表單清單 / 確認 三種狀態 */}
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
            ) : view === "forms" ? (
              <>
                {onAddImage && (
                  <button
                    onClick={() => setView("root")}
                    className="size-6 rounded hover:bg-zinc-100 flex items-center justify-center"
                    aria-label="返回"
                  >
                    <ArrowLeft size={14} className="text-zinc-500" />
                  </button>
                )}
                <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wide">
                  選擇表單
                </span>
              </>
            ) : (
              <span className="text-[11px] font-medium text-zinc-500 uppercase tracking-wide">
                新增
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
            ) : view === "root" ? (
              // ── root：選擇表單 / 上傳圖片 ─────────────
              <>
                <button
                  type="button"
                  onClick={() => setView("forms")}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-[14px] text-zinc-800 hover:bg-zinc-100 transition-colors"
                >
                  <Files size={15} className="shrink-0 text-zinc-500" />
                  <span className="flex-1">選擇表單</span>
                  <ChevronRight size={14} className="shrink-0 text-zinc-400" />
                </button>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-[14px] text-zinc-800 hover:bg-zinc-100 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <ImagePlus size={15} className="shrink-0 text-zinc-500" />
                  <span className="flex-1">{uploading ? "上傳中…" : "上傳圖片"}</span>
                </button>
                {canUploadDocument && (
                  <button
                    type="button"
                    onClick={() => docInputRef.current?.click()}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-[14px] text-zinc-800 hover:bg-zinc-100 transition-colors"
                  >
                    <Paperclip size={15} className="shrink-0 text-zinc-500" />
                    <span className="flex-1">上傳文件（PDF/Word/PPT）</span>
                  </button>
                )}
                {uploadError && (
                  <p className="px-3 pt-1 text-[12px] text-rose-500">{uploadError}</p>
                )}
              </>
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
                            "absolute z-10 rounded-lg border border-zinc-200 bg-white shadow-lg p-1",
                            // 桌面：彈到 active row 右側
                            "left-full top-0 ml-1 w-40",
                            // 手機：靠在該列右側內緣（不外溢）
                            "max-sm:left-auto max-sm:right-0 max-sm:ml-0 max-sm:w-36"
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
