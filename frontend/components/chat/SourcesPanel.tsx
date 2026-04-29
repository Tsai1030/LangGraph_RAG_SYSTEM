"use client";

import { useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Source } from "@/types";

interface Props { sources: Source[]; }

export default function SourcesPanel({ sources }: Props) {
  const[open, setOpen] = useState(false);
  if (!sources.length) return null;

  return (
    // ✨ 外框圓角加大：從 rounded-xl 改為 rounded-2xl
    <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm overflow-hidden">
      
      {/* --- 點擊觸發區 (Header) --- */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-2.5 bg-white hover:bg-zinc-50/80 transition-colors focus:outline-none"
      >
        <div className="flex items-center gap-2 text-zinc-700">
          <FileText className="w-3.5 h-3.5 text-zinc-400" />
          <span className="text-xs font-medium tracking-wide">參考來源</span>
        </div>

        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center justify-center px-1.5 py-0.5 rounded-full bg-zinc-100 border border-zinc-200/60 text-[10px] font-medium text-zinc-500">
            {sources.length} 份文件
          </span>
          <ChevronDown
            className={cn(
              "w-3.5 h-3.5 text-zinc-400 transition-transform duration-300 ease-in-out",
              open && "rotate-180"
            )}
          />
        </div>
      </button>

      {/* --- 展開內容區 --- */}
      <div
        className={cn(
          "grid transition-all duration-300 ease-in-out",
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-zinc-100 divide-y divide-zinc-100/80">
            {sources.map((src, i) => (
              <div 
                key={i} 
                className="px-4 py-3 hover:bg-zinc-50/60 transition-colors group cursor-pointer"
              >
                <div className="flex items-start gap-2.5">
                  
                  {/* ✨ 數字方塊圓角加大：從 rounded 改為 rounded-md，呼應外框的圓潤感 */}
                  <span className="shrink-0 flex items-center justify-center size-5 rounded-md bg-zinc-100/80 border border-zinc-200/60 text-[10px] font-semibold text-zinc-500 group-hover:bg-zinc-200 group-hover:text-zinc-700 transition-colors mt-0.5">
                    {i + 1}
                  </span>
                  
                  <div className="flex-1 min-w-0 flex flex-col gap-1">
                    
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[12px] text-zinc-800 font-medium truncate group-hover:text-zinc-950 transition-colors">
                        {src.source_file}
                      </p>
                      {/* 代碼標籤圓角也維持微圓潤 */}
                      <code className="shrink-0 px-1 py-0.5 rounded bg-zinc-100/80 border border-zinc-200/50 text-[9px] font-mono text-zinc-500">
                        {src.section_code}
                      </code>
                    </div>
                    
                    {src.section && (
                      <p className="text-[11px] text-zinc-500 truncate leading-relaxed">
                        {src.section}
                      </p>
                    )}
                    
                    {src.tags?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {src.tags.map((tag) => (
                          <span 
                            key={tag} 
                            className="px-1.5 py-0.5 rounded-full bg-white border border-zinc-200/80 text-[9.5px] text-zinc-500 shadow-sm leading-none flex items-center"
                          >
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
        </div>
      </div>
    </div>
  );
}