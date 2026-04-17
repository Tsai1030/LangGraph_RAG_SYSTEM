"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { getAccessToken } from "@/store/authStore";
import type { FormData } from "@/types";

interface Props { formData: FormData; filename?: string; }

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
    } catch {}
    finally { setLoading(null); }
  };

  return (
    <div className="flex gap-2 mt-2.5">
      {(["excel", "csv"] as const).map((type) => (
        <button
          key={type}
          onClick={() => download(type)}
          disabled={!!loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium border border-zinc-200 text-zinc-600 hover:text-zinc-900 hover:border-zinc-300 hover:bg-zinc-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors bg-white"
        >
          {loading === type ? (
            <span className="size-3 border border-zinc-400 border-t-transparent rounded-full animate-spin-fast" />
          ) : (
            <Download size={11} />
          )}
          {type === "excel" ? "下載 Excel" : "下載 CSV"}
        </button>
      ))}
    </div>
  );
}
