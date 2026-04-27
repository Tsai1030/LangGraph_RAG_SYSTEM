"use client";

import { useState } from "react";
import { FileText, Download } from "lucide-react";
import { getAccessToken } from "@/store/authStore";
import type { FormFile } from "@/types";

interface Props {
  file: FormFile;
}

export default function FormFileCard({ file }: Props) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const token = getAccessToken();
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
      const res = await fetch(`${backendUrl}${file.download_url}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("下載失敗");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${file.display_name}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <button
      onClick={handleDownload}
      disabled={downloading}
      className="flex items-center gap-3 w-full rounded-xl border border-zinc-200 bg-white px-4 py-3 text-left hover:border-zinc-300 hover:bg-zinc-50 hover:shadow-sm transition-all duration-150 disabled:opacity-60 disabled:cursor-not-allowed group"
    >
      <div className="shrink-0 size-9 rounded-lg bg-zinc-100 flex items-center justify-center group-hover:bg-zinc-200 transition-colors">
        <FileText size={16} className="text-zinc-500" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium text-zinc-800 truncate">
          {file.display_name}
        </p>
        <p className="text-[11px] text-zinc-400 mt-0.5">點擊下載 .docx</p>
      </div>
      <Download
        size={14}
        className="shrink-0 text-zinc-400 group-hover:text-zinc-600 transition-colors"
      />
    </button>
  );
}
