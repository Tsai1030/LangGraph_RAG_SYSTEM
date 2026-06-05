"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, Route, Receipt, ShieldCheck, Building2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { useChatStore } from "@/store/chatStore";
import type { ConversationOut, PendingImage } from "@/types";
import FormPickerButton from "@/components/chat/FormPickerButton";

const SUGGESTIONS = [
  { q: "工地施工動線規劃", icon: Route },
  { q: "採購發包的金額分級", icon: Receipt },
  { q: "安全衛生管理規定", icon: ShieldCheck },
  { q: "工務所辦公室設置說明", icon: Building2 },
];

export default function NewPage() {
  const router = useRouter();
  const { addConversation, setPendingMessage, setPendingImageIds } = useChatStore();
  const [creating, setCreating] = useState(false);
  const [value, setValue] = useState("");
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const addImage = (img: PendingImage) =>
    setPendingImages((prev) => [...prev, img]);
  const removeImage = (id: string) =>
    setPendingImages((prev) => {
      const found = prev.find((p) => p.image_id === id);
      if (found) URL.revokeObjectURL(found.preview_url);
      return prev.filter((p) => p.image_id !== id);
    });

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  };

  const handleSend = useCallback(async (text: string, imageIds: string[] = []) => {
    const msg = text.trim();
    if ((!msg && imageIds.length === 0) || creating) return;
    setCreating(true);
    try {
      const { data } = await api.post<ConversationOut>("/conversations", {});
      addConversation(data);
      setPendingMessage(msg);
      setPendingImageIds(imageIds);
      pendingImages.forEach((p) => URL.revokeObjectURL(p.preview_url));
      router.push(`/chat/${data.id}`);
    } catch {
      setCreating(false);
    }
  }, [creating, router, addConversation, setPendingMessage, setPendingImageIds, pendingImages]);

  const canSend = (value.trim().length > 0 || pendingImages.length > 0) && !creating;

  const inputBox = (placeholder: string) => (
    <div className={cn(
      "flex flex-col gap-2 rounded-4xl border bg-white shadow-sm px-3 py-3 transition-all duration-200",
      creating
        ? "border-zinc-200 opacity-60"
        : "border-zinc-200 hover:border-zinc-300 focus-within:border-zinc-400 focus-within:shadow-lg"
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
          onSendMessage={(msg) => handleSend(msg)}
          onAddImage={addImage}
          disabled={creating}
        />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            autoResize(e.target);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend(value, pendingImages.map((p) => p.image_id));
            }
          }}
          disabled={creating}
          placeholder={placeholder}
          rows={1}
          className="flex-1 text-base text-zinc-800 placeholder-zinc-400 bg-transparent outline-none resize-none leading-relaxed disabled:cursor-not-allowed"
          style={{ maxHeight: "180px", overflowY: "auto" }}
        />
        <button
          onClick={() => handleSend(value, pendingImages.map((p) => p.image_id))}
          disabled={!canSend}
          className={cn(
            "shrink-0 size-8 rounded-full flex items-center justify-center transition-all duration-150",
            canSend ? "bg-zinc-900 hover:bg-zinc-700 active:scale-95" : "bg-zinc-100 cursor-not-allowed"
          )}
          title="送出"
        >
          <ArrowUp size={14} className={canSend ? "text-white" : "text-zinc-400"} />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* ── Desktop layout ── */}
      <div className="hidden md:flex flex-col h-full items-center bg-dot-grid px-4 select-none overflow-y-auto">
        <div className="w-full max-w-2xl flex flex-col gap-5 mt-auto mb-auto py-[10vh]">
          {/* Brand mark */}
          <div className="flex flex-col items-center gap-3 mb-2">
            <div className="text-center">
              <h2 className="text-[2rem] font-bold tracking-tight text-zinc-900 leading-tight">
                有什麼可以幫您？
              </h2>
              <p className="text-[0.95rem] text-zinc-400 mt-1.5">
                查詢工地作業規範，或生成結構化作業表單
              </p>
            </div>
          </div>

          {/* Input */}
          {inputBox("輸入問題，例如：動員開工需要哪些初期計畫？")}
          <p className="text-center text-[11px] text-zinc-400 -mt-2 select-none">
            AI 有時會犯錯，需要二次查驗
          </p>

          {/* Suggestion cards */}
          <div className="grid grid-cols-2 gap-2.5">
            {SUGGESTIONS.map((item, i) => (
              <button
                key={item.q}
                onClick={() => handleSend(item.q)}
                disabled={creating}
                className="group animate-slide-up flex flex-col gap-3 px-4 py-4 rounded-2xl border border-zinc-200 bg-white text-left hover:border-zinc-300 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ animationDelay: `${i * 55}ms` }}
              >
                <item.icon
                  size={15}
                  className="text-zinc-400 group-hover:text-zinc-700 transition-colors duration-200"
                />
                <span className="text-[13px] text-zinc-600 group-hover:text-zinc-900 leading-snug transition-colors duration-200 font-medium">
                  {item.q}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Mobile layout ── */}
      <div className="md:hidden flex flex-col h-full bg-dot-grid select-none">
        <div className="flex-1 flex flex-col items-center justify-center px-6 pt-12 gap-3">
          <div className="text-center">
            <h2 className="text-2xl font-bold tracking-tight text-zinc-900">有什麼可以幫您？</h2>
            <p className="text-sm text-zinc-400 mt-1.5 text-center">查詢工地規範或生成作業表單</p>
          </div>
        </div>

        <div className="px-4 pb-6 flex flex-col gap-3">
          {inputBox("想問就問")}
          <p className="text-center text-[11px] text-zinc-400 select-none">
            AI 有時會犯錯，需要二次查驗
          </p>
        </div>
      </div>
    </>
  );
}
