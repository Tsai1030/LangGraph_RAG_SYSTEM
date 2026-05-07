"use client";

import { useEffect, useState } from "react";
import { Database } from "lucide-react";
import api from "@/lib/api";
import type { AdminVectorInfo } from "@/types/admin";

export default function AdminVectorPage() {
  const [info, setInfo] = useState<AdminVectorInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminVectorInfo>("/admin/vector/info")
      .then(({ data }) => setInfo(data))
      .catch(() => setError("載入向量庫資訊失敗"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-zinc-500">
        <span className="size-4 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast mr-2" />
        載入中…
      </div>
    );
  }

  if (error || !info) {
    return <div className="text-sm text-red-600">{error ?? "無資料"}</div>;
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold text-zinc-900">向量庫狀態</h2>
        <p className="text-sm text-zinc-500 mt-0.5">
          目前唯讀檢視。文件上傳與重建索引將在後續版本提供。
        </p>
      </div>

      {/* Active version */}
      <div className="bg-white border border-zinc-200 rounded-xl p-5">
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-3">
          設定
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <div className="text-[11px] text-zinc-500">啟用版本</div>
            <div className="text-sm text-zinc-900 font-medium mt-1">{info.active_version}</div>
          </div>
          <div className="min-w-0">
            <div className="text-[11px] text-zinc-500">解析路徑</div>
            <div className="text-sm text-zinc-900 mt-1 font-mono break-all">{info.resolved_path}</div>
          </div>
        </div>
      </div>

      {/* Collections */}
      <div>
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-3">
          Collections
        </h3>
        {info.collections.length === 0 && (
          <div className="text-sm text-zinc-500 bg-white border border-zinc-200 rounded-xl p-6 text-center">
            尚無 collection
          </div>
        )}
        <div className="flex flex-col gap-3">
          {info.collections.map((c) => (
            <div key={c.name} className="bg-white border border-zinc-200 rounded-xl p-5">
              <div className="flex items-center gap-2">
                <Database size={14} className="text-zinc-400" />
                <h4 className="text-sm font-medium text-zinc-900">{c.name}</h4>
                <span className="ml-auto text-sm text-zinc-700 tabular-nums">
                  {c.document_count.toLocaleString()} 個 chunk
                </span>
              </div>
              {c.sample_files.length > 0 && (
                <div className="mt-3 pt-3 border-t border-zinc-100">
                  <div className="text-[11px] text-zinc-500 mb-1.5">抽樣來源檔（前 50 筆中發現）</div>
                  <div className="flex flex-wrap gap-1.5">
                    {c.sample_files.map((f) => (
                      <span
                        key={f}
                        className="inline-block px-2 py-0.5 rounded text-[11px] bg-zinc-100 text-zinc-700 font-mono"
                      >
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
