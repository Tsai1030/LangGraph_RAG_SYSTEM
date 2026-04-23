"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Source } from "@/types";

interface Props { sources: Source[]; }

export default function SourcesPanel({ sources }: Props) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;

  return (
    <div className="rounded-xl border border-zinc-200 overflow-hidden text-xs bg-white shadow-sm">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-zinc-500 hover:text-zinc-700 hover:bg-zinc-50/80 transition-colors"
      >
        {/* Source count pill */}
        <span className="flex items-center justify-center size-4 rounded-full bg-zinc-100 text-[10px] font-semibold text-zinc-600 shrink-0">
          {sources.length}
        </span>
        <span className="font-medium text-[12px]">參考文件</span>
        <ChevronDown
          size={11}
          className={cn("ml-auto text-zinc-400 transition-transform duration-200", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="border-t border-zinc-100 divide-y divide-zinc-100">
          {sources.map((src, i) => (
            <div key={i} className="px-3 py-2.5 hover:bg-zinc-50/60 transition-colors">
              <div className="flex items-start gap-2.5">
                {/* Source number */}
                <span className="shrink-0 size-4 rounded-full bg-zinc-900 text-white flex items-center justify-center text-[9px] font-bold mt-0.5">
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-zinc-800 font-medium truncate text-[12px]">{src.source_file}</p>
                    <code className="shrink-0 px-1.5 py-0.5 rounded-md bg-zinc-100 text-zinc-500 text-[10px] font-mono">
                      {src.section_code}
                    </code>
                  </div>
                  {src.section && (
                    <p className="text-zinc-400 text-[11px] mt-0.5 truncate">{src.section}</p>
                  )}
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
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
