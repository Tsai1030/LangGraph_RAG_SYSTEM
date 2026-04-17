"use client";

import { useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Source } from "@/types";

interface Props { sources: Source[]; }

export default function SourcesPanel({ sources }: Props) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;

  return (
    <div className="rounded-xl border border-zinc-200 overflow-hidden text-xs bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-zinc-500 hover:text-zinc-700 hover:bg-zinc-50 transition-colors"
      >
        <FileText size={12} className="shrink-0 text-zinc-400" />
        <span className="font-medium">參考文件 · {sources.length} 筆</span>
        <ChevronDown
          size={12}
          className={cn("ml-auto transition-transform duration-200", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="border-t border-zinc-100">
          {sources.map((src, i) => (
            <div
              key={i}
              className={cn(
                "px-3 py-2.5 hover:bg-zinc-50 transition-colors",
                i < sources.length - 1 && "border-b border-zinc-100"
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-zinc-700 font-medium truncate text-[12px]">{src.source_file}</p>
                  {src.section && (
                    <p className="text-zinc-400 text-[11px] mt-0.5 truncate">{src.section}</p>
                  )}
                </div>
                <Badge variant="secondary" className="shrink-0 text-[10px] font-mono px-1.5 py-0">
                  {src.section_code}
                </Badge>
              </div>
              {src.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {src.tags.map((tag) => (
                    <span key={tag} className="px-1.5 py-0.5 rounded-md bg-zinc-100 text-zinc-500 text-[10px]">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
