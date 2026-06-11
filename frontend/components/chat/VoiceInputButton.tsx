"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Mic } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

export type VoiceState = "idle" | "recording" | "transcribing";

interface Props {
  disabled?: boolean;
  /** 轉錄成功時回傳文字（呼叫端自行附加到輸入框）。 */
  onTranscript: (text: string) => void;
  /** 錄音狀態變化（呼叫端可據此切換 placeholder）。 */
  onStateChange?: (state: VoiceState) => void;
  /** 錯誤訊息（null = 清除）。呼叫端決定顯示位置。 */
  onError?: (msg: string | null) => void;
}

/**
 * VoiceInputButton — 語音輸入（STT）麥克風按鈕。
 *
 * 按一下開始錄音（紅色脈動），再按一下結束 → POST /api/chat/transcribe
 * （AUDIO_MODEL，Gemini 多模態）→ onTranscript 回傳轉錄文字。
 * InputBar（聊天頁）與 /new（新對話頁）共用。
 * 瀏覽器不支援 MediaRecorder / 非 HTTPS（getUserMedia 拿不到）時不渲染。
 */
export default function VoiceInputButton({ disabled, onTranscript, onStateChange, onError }: Props) {
  const [recState, setRecStateRaw] = useState<VoiceState>("idle");
  const [supported, setSupported] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const setRecState = (s: VoiceState) => {
    setRecStateRaw(s);
    onStateChange?.(s);
  };

  useEffect(() => {
    // useEffect 內判斷支援度（避免 SSR/hydration 不一致）；getUserMedia 需要 HTTPS
    setSupported(
      typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia
    );
  }, []);

  // 卸載時停止錄音與麥克風（避免分頁仍顯示收音中）
  useEffect(() => {
    return () => {
      const rec = recorderRef.current;
      if (rec && rec.state !== "inactive") rec.stop();
      rec?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // 權限被封鎖時瀏覽器不會再跳詢問視窗，也沒有 API 能替使用者打開開關
  // （安全設計）→ 只能明確指引去網址列的權限設定。依錯誤類型給對應訊息。
  const micErrorMessage = (err: unknown): string => {
    const name = (err as DOMException)?.name ?? "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") {
      return "麥克風權限已被封鎖：請點瀏覽器網址列左側的「鎖頭／權限」圖示 → 麥克風 → 改為「允許」，然後重新整理頁面再試。";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return "找不到麥克風裝置：請確認麥克風已連接並啟用。";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "麥克風正被其他應用程式使用中，請關閉後再試。";
    }
    return "無法取得麥克風，請再試一次。";
  };

  const startRecording = async () => {
    onError?.(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Chrome/Edge/Firefox → webm(opus)；Safari → mp4。後端兩者皆收。
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) =>
        MediaRecorder.isTypeSupported(m)
      );
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (blob.size === 0) {
          setRecState("idle");
          return;
        }
        setRecState("transcribing");
        try {
          const fd = new FormData();
          fd.append("file", blob, "voice-input");
          const { data } = await api.post<{ text: string }>("/chat/transcribe", fd);
          if (data.text) {
            onTranscript(data.text);
          } else {
            onError?.("沒有聽到語音內容，請再試一次");
          }
        } catch {
          onError?.("語音轉錄失敗，請再試一次");
        } finally {
          setRecState("idle");
        }
      };
      rec.start();
      recorderRef.current = rec;
      setRecState("recording");
    } catch (err) {
      onError?.(micErrorMessage(err));
      setRecState("idle");
    }
  };

  const stopRecording = () => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
  };

  if (!supported) return null;

  const blocked = disabled || recState === "transcribing";

  return (
    <button
      type="button"
      onClick={recState === "recording" ? stopRecording : startRecording}
      disabled={blocked}
      className={cn(
        "shrink-0 size-8 rounded-full flex items-center justify-center transition-colors",
        recState === "recording"
          ? "bg-rose-500 hover:bg-rose-600 text-white animate-pulse"
          : "hover:bg-zinc-100 text-zinc-600 active:scale-95",
        blocked && "opacity-50 cursor-not-allowed"
      )}
      title={recState === "recording" ? "結束錄音" : "語音輸入"}
    >
      {recState === "transcribing" ? (
        <Loader2 size={16} className="animate-spin text-zinc-500" />
      ) : (
        <Mic size={16} />
      )}
    </button>
  );
}
