"use client";

import { useState } from "react";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { getAccessToken } from "@/store/authStore";
import type { FormData } from "@/types";

interface Props {
  formData: FormData;
  filename?: string;
}

export default function ExportButton({ formData, filename = "表單" }: Props) {
  const [loadingExcel, setLoadingExcel] = useState(false);
  const [loadingCsv, setLoadingCsv] = useState(false);

  const download = async (type: "excel" | "csv") => {
    const setLoading = type === "excel" ? setLoadingExcel : setLoadingCsv;
    setLoading(true);

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

      if (!res.ok) throw new Error("匯出失敗");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${filename}.${type === "excel" ? "xlsx" : "csv"}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export error:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex gap-2 mt-2">
      <button
        onClick={() => download("excel")}
        disabled={loadingExcel}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white transition-colors"
      >
        {loadingExcel ? (
          <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin-custom" />
        ) : (
          <FileSpreadsheet size={14} />
        )}
        下載 Excel
      </button>
      <button
        onClick={() => download("csv")}
        disabled={loadingCsv}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-600 hover:bg-slate-700 disabled:bg-slate-400 text-white transition-colors"
      >
        {loadingCsv ? (
          <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin-custom" />
        ) : (
          <FileText size={14} />
        )}
        下載 CSV
      </button>
    </div>
  );
}
