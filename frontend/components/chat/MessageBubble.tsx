"use client";

import { useState, useEffect, useCallback, useRef } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { X, Copy, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MessageOut, FormFile, Source } from "@/types";
import SourcesPanel from "./SourcesPanel";
import FormFileCard from "./FormFileCard";
import AuthImage from "./AuthImage";

interface Props {
  message: MessageOut;
  isStreaming?: boolean;
  isFormLoading?: boolean;
  isImageReading?: boolean;
  currentStep?: string | null;
  streamingSources?: Source[];
  streamingFormFiles?: FormFile[];
  onRetry?: (assistantMessageId: string) => void;
  retryDisabled?: boolean;
}

function MessageActions({
  content,
  onRetry,
  retryDisabled,
}: {
  content: string;
  onRetry?: () => void;
  retryDisabled?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  }, [content]);

  return (
    <div className="mt-2 flex items-center gap-1">
      {/* Copy */}
      <div className="group relative">
        <button
          onClick={handleCopy}
          aria-label="Copy"
          className={cn(
            "size-7 rounded flex items-center justify-center",
            "hover:bg-zinc-200/70 transition-colors"
          )}
        >
          <Copy size={13} className="text-zinc-500" />
        </button>
        <span
          className={cn(
            "pointer-events-none absolute top-9 left-1/2 -translate-x-1/2 z-10",
            "px-2 py-1 rounded-md whitespace-nowrap",
            "text-[11px] bg-zinc-900 text-white shadow-md transition-opacity",
            copied ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          )}
        >
          {copied ? "Copied" : "Copy"}
        </span>
      </div>

      {/* Retry */}
      {onRetry && (
        <div className="group relative">
          <button
            onClick={onRetry}
            disabled={retryDisabled}
            aria-label="Retry"
            className={cn(
              "size-7 rounded flex items-center justify-center transition-colors",
              "hover:bg-zinc-200/70",
              "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            )}
          >
            <RotateCw size={13} className="text-zinc-500" />
          </button>
          <span
            className={cn(
              "pointer-events-none absolute top-9 left-1/2 -translate-x-1/2 z-10",
              "px-2 py-1 rounded-md whitespace-nowrap",
              "text-[11px] bg-zinc-900 text-white shadow-md transition-opacity",
              "opacity-0 group-hover:opacity-100",
              retryDisabled && "group-hover:opacity-0"
            )}
          >
            Retry
          </span>
        </div>
      )}
    </div>
  );
}

function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 bg-opacity-40 backdrop-blur-[2px] p-4"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 size-9 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
      >
        <X size={18} />
      </button>
      <img
        src={src}
        alt={alt}
        className="max-h-[90vh] max-w-[90vw] rounded-lg shadow-2xl object-contain"
        onClick={(e) => e.stopPropagation()}
      />
      {alt && (
        <p className="absolute bottom-6 left-1/2 -translate-x-1/2 text-white/70 text-sm bg-black/40 px-3 py-1 rounded-full">
          {alt}
        </p>
      )}
    </div>
  );
}

/** 將 DOM table 轉回 markdown（純文字版）給複製用。 */
function tableElementToMarkdown(table: HTMLTableElement): string {
  const rowToCells = (tr: HTMLTableRowElement): string[] =>
    Array.from(tr.querySelectorAll("th, td")).map((c) =>
      (c.textContent ?? "").trim().replace(/\s*\|\s*/g, "\\|")
    );

  const headerEl = table.querySelector("thead tr") as HTMLTableRowElement | null;
  const bodyRows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];

  const headerCells = headerEl ? rowToCells(headerEl) : [];
  // 若沒有 thead，把 tbody 第一列當 header
  const fallbackHeader = !headerEl && bodyRows.length > 0 ? rowToCells(bodyRows[0]) : null;
  const dataRows = (fallbackHeader ? bodyRows.slice(1) : bodyRows).map(rowToCells);
  const finalHeader = headerCells.length ? headerCells : fallbackHeader ?? [];
  if (!finalHeader.length) return "";

  const colCount = finalHeader.length;
  const lines = [
    "| " + finalHeader.join(" | ") + " |",
    "|" + Array(colCount).fill("---").join("|") + "|",
    ...dataRows.map((r) => "| " + r.concat(Array(colCount - r.length).fill("")).join(" | ") + " |"),
  ];
  return lines.join("\n");
}

/** 表格容器：橫向 scroll + hover 時左上角顯示複製按鈕（複製 markdown 格式）。 */
function TableWithCopy({ children }: { children: React.ReactNode }) {
  const tableRef = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    const t = tableRef.current;
    if (!t) return;
    const md = tableElementToMarkdown(t);
    if (!md) return;
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 寫入失敗（e.g. 沒授權）忽略；可未來補 toast
    }
  }, []);

  return (
    <div className="group relative my-3 max-w-full overflow-x-auto">
      {/* 複製按鈕 — 表格 hover 才顯出；按鈕 hover 顯示淺灰底 + 下方 tooltip */}
      <button
        onClick={handleCopy}
        aria-label="複製表格"
        className={cn(
          "peer absolute top-1 right-1 z-10 size-7 rounded flex items-center justify-center",
          "opacity-0 group-hover:opacity-100 transition-opacity",
          "hover:bg-zinc-200/70"
        )}
      >
        <Copy size={13} className="text-zinc-500" />
      </button>
      <span
        className={cn(
          "pointer-events-none absolute top-9 right-1 z-10 px-2 py-1 rounded-md whitespace-nowrap",
          "text-[11px] bg-zinc-900 text-white shadow-md transition-opacity",
          copied ? "opacity-100" : "opacity-0 peer-hover:opacity-100"
        )}
      >
        {copied ? "已複製" : "複製表格"}
      </span>
      <table ref={tableRef} className="!my-0">{children}</table>
    </div>
  );
}

function createMarkdownComponents(onImageClick: (src: string, alt: string) => void): Components {
  return {
    p: ({ children }) => <div className="my-1.5 leading-relaxed">{children}</div>,
    img: (props) => {
      const src = typeof props.src === "string" ? props.src : undefined;
      const alt = typeof props.alt === "string" ? props.alt : "";
      return (
        <figure className="my-3">
          <img
            src={src}
            alt={alt}
            className="max-w-full rounded-lg border border-zinc-200 shadow-sm cursor-zoom-in"
            onClick={() => src && onImageClick(src, alt)}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
          {alt && <figcaption className="text-[11px] text-zinc-400 mt-1.5 text-center">{alt}</figcaption>}
        </figure>
      );
    },
    // 表格寬於聊天區時，把橫向 scroll 限制在表格自己的容器，
    // 避免整個聊天視窗被推寬產生外層 horizontal scroll
    table: ({ children }) => <TableWithCopy>{children}</TableWithCopy>,
  };
}

function ThinkingText({ step }: { step?: string | null }) {
  return (
    <span className="text-sm font-medium tracking-wide thinking-gradient select-none">
      {step || "Thinking…"}
    </span>
  );
}

function GeneratingTableText() {
  return (
    <span className="text-sm font-medium tracking-wide thinking-gradient select-none">
      Generating table…
    </span>
  );
}

function ImageReadingText() {
  return (
    <span className="text-sm font-medium tracking-wide thinking-gradient select-none">
      Analyzing image...
    </span>
  );
}

export default function MessageBubble({
  message, isStreaming = false, isFormLoading = false, isImageReading = false, currentStep, streamingSources, streamingFormFiles,
  onRetry, retryDisabled = false,
}: Props) {
  const isUser = message.role === "user";
  const sources: Source[] = streamingSources ?? message.meta?.sources ?? [];
  const formFiles: FormFile[] =
    streamingFormFiles !== undefined ? (streamingFormFiles ?? []) : (message.meta?.form_files ?? []);

  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null);
  const handleImageClick = useCallback((src: string, alt: string) => setLightbox({ src, alt }), []);
  const markdownComponents = createMarkdownComponents(handleImageClick);

  if (isUser) {
    const images = message.meta?.images ?? [];
    return (
      <>
        {lightbox && (
          <Lightbox src={lightbox.src} alt={lightbox.alt} onClose={() => setLightbox(null)} />
        )}
        <div className="flex justify-end px-6 animate-fade-up">
          <div className="max-w-[72%] flex flex-col items-end gap-2">
            {images.length > 0 && (
              <div className="flex flex-wrap gap-2 justify-end">
                {images.map((img) => (
                  <AuthImage
                    key={img.image_id}
                    imageId={img.image_id}
                    className="size-28 rounded-xl object-cover border border-zinc-200 cursor-zoom-in"
                    onClick={(url) => handleImageClick(url, "")}
                  />
                ))}
              </div>
            )}
            {message.content && (
              <div className="bg-zinc-900 text-zinc-100 px-4 py-3 rounded-2xl rounded-br-sm text-base leading-relaxed whitespace-pre-wrap shadow-sm">
                {message.content}
              </div>
            )}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {lightbox && (
        <Lightbox src={lightbox.src} alt={lightbox.alt} onClose={() => setLightbox(null)} />
      )}
      <div className="flex items-start px-4 md:px-6 animate-fade-up">
        <div className="flex-1 min-w-0 pb-1">
          {/* Message content（含動態表單的 markdown 表格 — 由 backend 寫進 content）*/}
          <div className={cn("prose-chat text-[15px]", isStreaming && !message.content && "py-1")}>
            {message.content ? (
              <div className={cn(isStreaming && "streaming-cursor")}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {message.content}
                </ReactMarkdown>
              </div>
            ) : isFormLoading ? (
              <GeneratingTableText />
            ) : isImageReading ? (
              <ImageReadingText />
            ) : (
              <ThinkingText step={currentStep} />
            )}
          </div>

          {/* 表單下載卡（靜態下載 / 已填寫 / 動態匯出）*/}
          {formFiles.length > 0 && !isStreaming && (
            <div className="mt-3 flex flex-col gap-2">
              {formFiles.map((f) => (
                <FormFileCard key={f.form_id} file={f} />
              ))}
            </div>
          )}

          {/* Sources */}
          {sources.length > 0 && !isStreaming && (
            <div className="mt-3">
              <SourcesPanel sources={sources} />
            </div>
          )}

          {/* Copy / Retry — 串流中不顯示，避免使用者按到還沒完成的訊息 */}
          {!isStreaming && message.content && (
            <MessageActions
              content={message.content}
              onRetry={onRetry ? () => onRetry(message.id) : undefined}
              retryDisabled={retryDisabled}
            />
          )}
        </div>
      </div>
    </>
  );
}
