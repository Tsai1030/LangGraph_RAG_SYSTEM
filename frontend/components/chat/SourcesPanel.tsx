"use client";

import { useState } from "react";
import { ChevronDown, BookOpen } from "lucide-react";
import type { Source } from "@/types";

interface Props {
  sources: Source[];
}

export default function SourcesPanel({ sources }: Props) {
  const [open, setOpen] = useState(false);

  if (!sources.length) return null;

  return (
    <div className="mt-2 rounded-lg border border-slate-200 overflow-hidden text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 transition-colors text-slate-600 font-medium"
      >
        <BookOpen size={12} className="text-blue-500 shrink-0" />
        <span>參考來源（{sources.length} 筆）</span>
        <ChevronDown
          size={13}
          className={`ml-auto transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="divide-y divide-slate-100">
          {sources.map((src, i) => (
            <div key={i} className="px-3 py-2 bg-white hover:bg-slate-50 transition-colors">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-slate-700 font-medium truncate">{src.source_file}</p>
                  {src.section && (
                    <p className="text-slate-400 mt-0.5 truncate">{src.section}</p>
                  )}
                </div>
                <span className="shrink-0 text-[10px] font-mono text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">
                  {src.section_code}
                </span>
              </div>
              {src.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {src.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 text-[10px]"
                    >
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
