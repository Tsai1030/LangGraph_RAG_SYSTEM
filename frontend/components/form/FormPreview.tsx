"use client";

import type { FormData } from "@/types";

export default function FormPreview({ formData }: { formData: FormData }) {
  const { title, subtitle, columns, rows, notes } = formData;

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm overflow-hidden">
      
      {/* --- Header (標題區) --- */}
      {/* Padding 微調為 px-5 py-4，字體改為 text-sm (14px) */}
      <div className="px-5 py-4 border-b border-zinc-100">
        <h3 className="text-sm font-semibold text-zinc-900 tracking-tight">
          {title}
        </h3>
        {subtitle && (
          /* 字體改為 text-xs (12px) */
          <p className="text-xs text-zinc-500 mt-0.5">
            {subtitle}
          </p>
        )}
      </div>

      {/* --- Table (表格區) --- */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-zinc-50/50 border-b border-zinc-100">
              {columns.map((col) => (
                <th
                  key={col}
                  /* Padding 縮小，字體改為 text-[11px] 保持大寫英文的精緻感 */
                  className="px-5 py-2.5 text-[11px] font-medium text-zinc-500 uppercase tracking-wider whitespace-nowrap"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          
          <tbody className="divide-y divide-zinc-100">
            {rows.map((row, i) => (
              <tr 
                key={i} 
                className="hover:bg-zinc-50/80 transition-colors duration-200 group cursor-pointer"
              >
                {columns.map((col) => {
                  const cellData = row[col];
                  return (
                    <td 
                      key={col} 
                      /* 資料字體改為 text-[13px] (介於 sm 與 xs 之間，最適合數據表格) */
                      className="px-5 py-3 text-[13px] text-zinc-700 align-middle"
                    >
                      {cellData ? cellData : <span className="text-zinc-300">-</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* --- Notes (備註區) --- */}
      {notes && (
        <div className="bg-zinc-50/80 border-t border-zinc-100 px-5 py-3.5 flex gap-3 items-start">
          {/* Badge 字體縮小到 text-[10px]，並縮減高度 */}
          <span className="shrink-0 inline-flex items-center rounded-md bg-zinc-200/50 px-2 py-0.5 text-[10px] font-medium text-zinc-600 ring-1 ring-inset ring-zinc-500/10 mt-0.5">
            備註
          </span>
          {/* 備註內文改為 text-[13px] */}
          <p className="text-[13px] text-zinc-600 leading-relaxed">
            {notes}
          </p>
        </div>
      )}
    </div>
  );
}