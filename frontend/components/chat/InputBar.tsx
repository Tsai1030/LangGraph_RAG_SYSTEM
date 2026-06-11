"use client";

import { useRef, useState, useEffect } from "react";
import { ArrowUp, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";
import DocumentCard from "./DocumentCard";
import FormPickerButton from "./FormPickerButton";
import VoiceInputButton, { type VoiceState } from "./VoiceInputButton";
import type { PendingDocument, PendingImage } from "@/types";

interface Props {
  onSend: (message: string, imageIds?: string[], documents?: PendingDocument[]) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  /** 文件上傳需要綁對話（索引存 session_{conversationId}）；未提供時不開放文件上傳 */
  conversationId?: string;
}

export default function InputBar({ onSend, onStop, isStreaming, disabled, conversationId }: Props) {
  const [value, setValue] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [pendingDocs, setPendingDocs] = useState<PendingDocument[]>([]);
  const [docError, setDocError] = useState<string | null>(null);
  // ── 語音輸入（STT）：VoiceInputButton 錄音轉錄，這裡只管 placeholder 與錯誤顯示 ──
  const [recState, setRecState] = useState<VoiceState>("idle");
  const [sttError, setSttError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const handleTranscript = (text: string) => {
    setValue((v) => (v.trim() ? v.trimEnd() + " " + text : text));
    ref.current?.focus();
  };

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  const addImage = (img: PendingImage) =>
    setPendingImages((prev) => [...prev, img]);

  const removeImage = (id: string) =>
    setPendingImages((prev) => {
      const found = prev.find((p) => p.image_id === id);
      if (found) URL.revokeObjectURL(found.preview_url);
      return prev.filter((p) => p.image_id !== id);
    });

  // 文件上傳三段式：選檔即顯示 skeleton 卡 → 完成換成正式卡 → 失敗移除並顯示錯誤
  const startDocument = (doc: PendingDocument) => {
    setDocError(null);
    setPendingDocs((prev) => [...prev, doc]);
  };

  const finishDocument = (tempId: string, doc: PendingDocument) =>
    setPendingDocs((prev) => prev.map((p) => (p.document_id === tempId ? doc : p)));

  const failDocument = (tempId: string, message: string) => {
    setPendingDocs((prev) => prev.filter((p) => p.document_id !== tempId));
    setDocError(message);
  };

  const removeDocument = (id: string) =>
    setPendingDocs((prev) => prev.filter((p) => p.document_id !== id));

  const isDocUploading = pendingDocs.some((p) => p.status === "uploading");

  const handleSend = () => {
    const msg = value.trim();
    if ((!msg && pendingImages.length === 0 && pendingDocs.length === 0) || isStreaming || disabled) return;
    if (isDocUploading) return; // 文件解析索引中，等完成再送出
    const ids = pendingImages.map((p) => p.image_id);
    const docs = pendingDocs;
    pendingImages.forEach((p) => URL.revokeObjectURL(p.preview_url));
    setValue("");
    setPendingImages([]);
    setPendingDocs([]);
    onSend(msg, ids, docs);
  };

  const canSend =
    (value.trim().length > 0 || pendingImages.length > 0 || pendingDocs.length > 0) &&
    !isDocUploading &&
    !isStreaming &&
    !disabled;

  return (
    <div className="px-4 pb-4">
      <div className="max-w-3xl mx-auto">
        <div className={cn(
          "flex flex-col gap-2 rounded-4xl border bg-white shadow-sm px-3 py-3 transition-all duration-200",
          disabled ? "border-zinc-200 opacity-60" : "border-zinc-200 hover:border-zinc-300 focus-within:border-zinc-400 focus-within:shadow-lg"
        )}>
          {pendingDocs.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {pendingDocs.map((doc) => (
                <DocumentCard key={doc.document_id} doc={doc} onRemove={removeDocument} />
              ))}
            </div>
          )}

          {pendingImages.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1">
              {pendingImages.map((img) => (
                <div key={img.image_id} className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={img.preview_url}
                    alt={img.name}
                    className="size-14 rounded-lg object-cover border border-zinc-200"
                  />
                  <button
                    type="button"
                    onClick={() => removeImage(img.image_id)}
                    className="absolute -top-1.5 -right-1.5 size-5 rounded-full bg-zinc-800 hover:bg-zinc-700 text-white flex items-center justify-center shadow"
                    title="移除"
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-end gap-2">
            <FormPickerButton
              onSendMessage={(msg) => onSend(msg)}
              onAddImage={addImage}
              onDocumentUploadStart={startDocument}
              onDocumentUploadDone={finishDocument}
              onDocumentUploadError={failDocument}
              getConversationId={
                conversationId ? async () => conversationId : undefined
              }
              disabled={disabled || isStreaming}
            />
            <textarea
              ref={ref}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
              }}
              disabled={disabled}
              placeholder={
                recState === "recording" ? "錄音中…再按一下麥克風結束"
                : recState === "transcribing" ? "語音轉錄中…"
                : isStreaming ? "回覆中…"
                : isMobile ? "想問就問"
                : "輸入問題，例如：動員開工需要哪些初期計畫？"
              }
              rows={1}
              className="flex-1 text-base text-zinc-800 placeholder-zinc-400 bg-transparent outline-none resize-none leading-relaxed disabled:cursor-not-allowed"
              style={{ maxHeight: "180px", overflowY: "auto" }}
            />

            <VoiceInputButton
              disabled={disabled || isStreaming}
              onTranscript={handleTranscript}
              onStateChange={setRecState}
              onError={setSttError}
            />

            {isStreaming ? (
              <button
                onClick={onStop}
                className="shrink-0 size-8 rounded-full bg-zinc-900 hover:bg-zinc-700 flex items-center justify-center transition-colors"
                title="停止"
              >
                <Square size={12} className="text-white fill-white" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!canSend}
                className={cn(
                  "shrink-0 size-8 rounded-full flex items-center justify-center transition-all duration-150",
                  canSend ? "bg-zinc-900 hover:bg-zinc-700 active:scale-95" : "bg-zinc-100 cursor-not-allowed"
                )}
                title="送出"
              >
                <ArrowUp size={14} className={canSend ? "text-white" : "text-zinc-400"} />
              </button>
            )}
          </div>

          {sttError && (
            <p className="px-1 text-[12px] text-rose-500">{sttError}</p>
          )}
          {docError && (
            <p className="px-1 text-[12px] text-rose-500">{docError}</p>
          )}
        </div>
        <p className="text-center text-[11px] text-zinc-400 mt-1.5 select-none">
          AI有時會犯錯·需要二次查驗
        </p>
      </div>
    </div>
  );
}
