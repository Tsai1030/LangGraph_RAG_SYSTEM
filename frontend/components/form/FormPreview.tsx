"use client";

import { Separator } from "@/components/ui/separator";
import type { FormData } from "@/types";

export default function FormPreview({ formData }: { formData: FormData }) {
  const { title, subtitle, columns, rows, notes } = formData;

  return (
    <div className="rounded-xl border border-zinc-200 overflow-hidden bg-white shadow-sm text-sm">
      {/* Header */}
      <div className="px-4 py-3 bg-zinc-50 border-b border-zinc-200">
        <p className="font-semibold text-zinc-800 text-[13px]">{title}</p>
        {subtitle && <p className="text-zinc-500 text-xs mt-0.5">{subtitle}</p>}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr className="bg-zinc-50/70">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-3 py-2 text-left font-semibold text-zinc-500 uppercase tracking-wide text-[10px] border-b border-zinc-200 whitespace-nowrap"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-zinc-100 last:border-b-0 hover:bg-zinc-50/50 transition-colors">
                {columns.map((col) => (
                  <td key={col} className="px-3 py-2.5 text-zinc-700 align-top">
                    {row[col] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Notes */}
      {notes && (
        <>
          <Separator />
          <div className="px-4 py-2.5 bg-zinc-50">
            <p className="text-[11px] text-zinc-500">
              <span className="font-medium text-zinc-600">備註　</span>{notes}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
