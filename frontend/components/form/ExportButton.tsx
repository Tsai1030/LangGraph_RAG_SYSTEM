"use client";

import { useState } from "react";
import { Loader2, FileSpreadsheet, FileText } from "lucide-react";
import { getAccessToken } from "@/store/authStore";
import type { FormData } from "@/types";

interface Props { 
  formData: FormData; 
  filename?: string; 
}

const EXPORT_OPTIONS =[
  { type: "excel", label: "下載 Excel", Icon: FileSpreadsheet },
  { type: "csv", label: "下載 CSV", Icon: FileText },
] as const;

export default function ExportButton({ formData, filename = "表單" }: Props) {
  const [loading, setLoading] = useState<"excel" | "csv" | null>(null);

  const download = async (type: "excel" | "csv") => {
    if (loading) return;
    setLoading(type);
    try {
      const token = getAccessToken();
      const res = await fetch(`/api/export/${type}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ form_data: formData, filename }),
      });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${filename}.${type === "excel" ? "xlsx" : "csv"}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // 可以在這裡加入 Toast 錯誤提示
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2.5 mt-3">
      {EXPORT_OPTIONS.map(({ type, label, Icon }) => (
        <button
          key={type}
          onClick={() => download(type)}
          disabled={!!loading}
          className={`
            group relative inline-flex items-center gap-1.5 
            
            /*  尺寸縮小：Padding 與字體微調，呼應表格的 13px */
            px-3.5 py-1.5 text-[13px] font-medium 
            
            /*  圓角加大：改用 rounded-full 變成精緻的膠囊狀 (Pill) */
            rounded-full 
            
            bg-white border border-zinc-200 shadow-sm text-zinc-700 
            transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-zinc-900/10
            
            /*  懸浮 (Hover) 特效：稍微變深 + 向上浮起 + 陰影變大 */
            hover:bg-zinc-50 hover:border-zinc-300 hover:text-zinc-900 
            hover:-translate-y-[1.5px] hover:shadow-md
            
            /*  點擊 (Active) 特效：往下壓的物理回饋 */
            active:scale-[0.97] active:translate-y-0 active:shadow-sm
            
            /*  禁用 (Disabled / Loading) 狀態 */
            disabled:opacity-50 disabled:cursor-not-allowed 
            disabled:hover:translate-y-0 disabled:hover:shadow-sm disabled:hover:bg-white disabled:hover:border-zinc-200
          `}
        >
          {loading === type ? (
            /* 圖示也稍微縮小一點點 (w-3.5 h-3.5) 以配合 13px 的文字 */
            <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-500" />
          ) : (
            <Icon className="w-3.5 h-3.5 text-zinc-400 transition-colors group-hover:text-zinc-600" />
          )}
          {label}
        </button>
      ))}
    </div>
  );
}