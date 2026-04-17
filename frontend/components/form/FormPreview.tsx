"use client";

import type { FormData } from "@/types";

interface Props {
  formData: FormData;
}

export default function FormPreview({ formData }: Props) {
  const { title, subtitle, columns, rows, notes } = formData;

  return (
    <div className="mt-3 rounded-xl border border-blue-100 overflow-hidden shadow-sm bg-white">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-4 py-3">
        <p className="text-white font-semibold text-sm">{title}</p>
        {subtitle && (
          <p className="text-blue-200 text-xs mt-0.5">{subtitle}</p>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-4 py-2.5 text-left font-semibold text-slate-600 text-xs uppercase tracking-wide whitespace-nowrap border-r border-slate-200 last:border-r-0"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-slate-100 hover:bg-blue-50/40 transition-colors"
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className="px-4 py-2.5 text-slate-700 border-r border-slate-100 last:border-r-0 align-top"
                  >
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
        <div className="px-4 py-2.5 bg-amber-50 border-t border-amber-100">
          <p className="text-xs text-amber-800">
            <span className="font-semibold">備註：</span>
            {notes}
          </p>
        </div>
      )}
    </div>
  );
}
