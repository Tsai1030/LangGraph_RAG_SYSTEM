"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MessageOut, FormData as FormDataType, Source } from "@/types";
import SourcesPanel from "./SourcesPanel";
import FormPreview from "@/components/form/FormPreview";
import ExportButton from "@/components/form/ExportButton";

interface Props {
  message: MessageOut;
  isStreaming?: boolean;
  streamingSources?: Source[];
  streamingFormData?: FormDataType | null;
}

function Lightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
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
  };
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 h-5 py-1">
      {[0, 200, 400].map((delay) => (
        <span
          key={delay}
          className="size-1.5 rounded-full bg-zinc-300"
          style={{ animation: `pulseDot 1.4s ease-in-out ${delay}ms infinite` }}
        />
      ))}
    </div>
  );
}

export default function MessageBubble({
  message, isStreaming = false, streamingSources, streamingFormData,
}: Props) {
  const isUser = message.role === "user";
  const sources: Source[] = streamingSources ?? message.meta?.sources ?? [];
  const formData: FormDataType | null | undefined =
    streamingFormData !== undefined ? streamingFormData : message.meta?.form_data;

  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null);
  const handleImageClick = useCallback((src: string, alt: string) => setLightbox({ src, alt }), []);
  const markdownComponents = createMarkdownComponents(handleImageClick);

  if (isUser) {
    return (
      <div className="flex justify-end px-6 animate-fade-up">
        <div className="max-w-[72%]">
          <div className="bg-zinc-900 text-zinc-100 px-4 py-3 rounded-2xl rounded-br-sm text-sm leading-relaxed whitespace-pre-wrap shadow-sm">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {lightbox && (
        <Lightbox src={lightbox.src} alt={lightbox.alt} onClose={() => setLightbox(null)} />
      )}
      <div className="flex gap-3 px-4 md:px-6 animate-fade-up">
        {/* Avatar — hidden on mobile */}
        <div className="hidden md:block shrink-0 size-6 mt-1">
          <Image src="/logo.png" alt="AI" width={24} height={24} className="size-6 object-contain" />
        </div>

        <div className="flex-1 min-w-0 pb-1">
          {/* Message content */}
          <div className={cn("prose-chat text-sm", isStreaming && !message.content && "py-1")}>
            {message.content ? (
              <div className={cn(isStreaming && "streaming-cursor")}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {message.content}
                </ReactMarkdown>
              </div>
            ) : (
              <ThinkingDots />
            )}
          </div>

          {/* Form preview */}
          {formData && (
            <div className="mt-3">
              <FormPreview formData={formData} />
              <ExportButton formData={formData} filename={formData.title} />
            </div>
          )}

          {/* Sources */}
          {sources.length > 0 && !isStreaming && (
            <div className="mt-3">
              <SourcesPanel sources={sources} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
