"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
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

const markdownComponents: Components = {
  img: (props) => {
    const src = typeof props.src === "string" ? props.src : undefined;
    const alt = typeof props.alt === "string" ? props.alt : "";
    return (
      <figure className="my-2">
        <img
          src={src}
          alt={alt}
          className="max-w-full rounded-lg border border-slate-200 cursor-zoom-in hover:shadow-md transition-shadow"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
        {alt && (
          <figcaption className="text-[11px] text-slate-400 mt-1 text-center">
            {alt}
          </figcaption>
        )}
      </figure>
    );
  },
};

export default function MessageBubble({
  message,
  isStreaming = false,
  streamingSources,
  streamingFormData,
}: Props) {
  const isUser = message.role === "user";
  const sources: Source[] =
    streamingSources ?? message.meta?.sources ?? [];
  const formData: FormDataType | null | undefined =
    streamingFormData !== undefined ? streamingFormData : message.meta?.form_data;

  if (isUser) {
    return (
      <div className="flex justify-end px-4 animate-fade-slide-in">
        <div className="max-w-[75%]">
          <div className="bg-blue-600 text-white px-4 py-3 rounded-2xl rounded-br-sm text-sm leading-relaxed shadow-sm whitespace-pre-wrap">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 px-4 animate-fade-slide-in">
      {/* Avatar */}
      <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center mt-0.5 shadow-sm">
        <span className="text-white text-xs font-bold">AI</span>
      </div>

      <div className="flex-1 min-w-0">
        {/* Message bubble */}
        <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
          <div className={`prose-chat text-sm ${isStreaming && !message.content ? "text-slate-400" : ""}`}>
            {message.content ? (
              <div className={isStreaming ? "streaming-cursor" : ""}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="flex items-center gap-1 h-5">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="w-1.5 h-1.5 rounded-full bg-blue-400"
                    style={{ animation: `pulse-dot 1.2s ease-in-out ${delay}ms infinite` }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Form preview */}
        {formData && (
          <div>
            <FormPreview formData={formData} />
            <ExportButton formData={formData} filename={formData.title} />
          </div>
        )}

        {/* Sources */}
        {sources.length > 0 && !isStreaming && (
          <SourcesPanel sources={sources} />
        )}
      </div>
    </div>
  );
}
