"use client";

import { useRef, useState, useEffect } from "react";
import { ArrowUp, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";
import FormPickerButton from "./FormPickerButton";
import type { PendingImage } from "@/types";

interface Props {
  onSend: (message: string, imageIds?: string[]) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export default function InputBar({ onSend, onStop, isStreaming, disabled }: Props) {
  const [value, setValue] = useState("");
  const [isMobile, setIsMobile] = useState(false);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

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

  const handleSend = () => {
    const msg = value.trim();
    if ((!msg && pendingImages.length === 0) || isStreaming || disabled) return;
    const ids = pendingImages.map((p) => p.image_id);
    pendingImages.forEach((p) => URL.revokeObjectURL(p.preview_url));
    setValue("");
    setPendingImages([]);
    onSend(msg, ids);
  };

  const canSend =
    (value.trim().length > 0 || pendingImages.length > 0) &&
    !isStreaming &&
    !disabled;

  return (
    <div className="px-4 pb-4">
      <div className="max-w-3xl mx-auto">
        <div className={cn(
          "flex flex-col gap-2 rounded-4xl border bg-white shadow-sm px-3 py-3 transition-all duration-200",
          disabled ? "border-zinc-200 opacity-60" : "border-zinc-200 hover:border-zinc-300 focus-within:border-zinc-400 focus-within:shadow-lg"
        )}>
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
              placeholder={isStreaming ? "回覆中…" : isMobile ? "想問就問" : "輸入問題，例如：動員開工需要哪些初期計畫？"}
              rows={1}
              className="flex-1 text-base text-zinc-800 placeholder-zinc-400 bg-transparent outline-none resize-none leading-relaxed disabled:cursor-not-allowed"
              style={{ maxHeight: "180px", overflowY: "auto" }}
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
        </div>
        <p className="text-center text-[11px] text-zinc-400 mt-1.5 select-none">
          AI有時會犯錯·需要二次查驗
        </p>
      </div>
    </div>
  );
}
