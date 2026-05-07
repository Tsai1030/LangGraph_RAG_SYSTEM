"use client";

import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@/lib/utils";
import type { AdminTimeSeriesPoint } from "@/types/admin";

type Metric = "messages" | "conversations" | "tokens";

const METRIC_META: Record<Metric, { label: string; color: string; gradientId: string }> = {
  messages:      { label: "訊息",   color: "#6366f1", gradientId: "g-msg"   }, // indigo-500
  conversations: { label: "對話",   color: "#10b981", gradientId: "g-conv"  }, // emerald-500
  tokens:        { label: "Tokens", color: "#f59e0b", gradientId: "g-token" }, // amber-500
};

function formatTick(date: string) {
  // date = "YYYY-MM-DD"
  const [, m, d] = date.split("-");
  return `${parseInt(m, 10)}/${parseInt(d, 10)}`;
}

function formatNumber(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function TimeSeriesChart({
  points,
  className,
}: {
  points: AdminTimeSeriesPoint[];
  className?: string;
}) {
  const [metric, setMetric] = useState<Metric>("messages");
  const meta = METRIC_META[metric];

  const totals = useMemo(() => {
    return points.reduce(
      (acc, p) => ({
        messages: acc.messages + p.messages,
        conversations: acc.conversations + p.conversations,
        tokens: acc.tokens + p.tokens,
      }),
      { messages: 0, conversations: 0, tokens: 0 }
    );
  }, [points]);

  return (
    <div className={cn("bg-white border border-zinc-200 rounded-xl p-5", className)}>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">每日趨勢</h3>
          <p className="text-xs text-zinc-500 mt-0.5">UTC 日期粒度</p>
        </div>
        <div className="flex items-center gap-1 bg-zinc-100 rounded-lg p-0.5">
          {(Object.keys(METRIC_META) as Metric[]).map((m) => {
            const active = m === metric;
            return (
              <button
                key={m}
                onClick={() => setMetric(m)}
                className={cn(
                  "px-3 py-1.5 text-xs rounded-md transition-colors tabular-nums",
                  active
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-600 hover:text-zinc-900"
                )}
              >
                {METRIC_META[m].label}
                <span className="ml-1.5 text-[11px] text-zinc-400">
                  {formatNumber(totals[m])}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="h-64 -ml-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={meta.gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={meta.color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={meta.color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatTick}
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={formatNumber}
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={40}
              allowDecimals={false}
            />
            <Tooltip
              cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }}
              contentStyle={{
                backgroundColor: "white",
                border: "1px solid #e4e4e7",
                borderRadius: 8,
                fontSize: 12,
                padding: "8px 10px",
                boxShadow: "0 4px 12px rgba(0,0,0,0.06)",
              }}
              labelStyle={{ color: "#71717a", fontSize: 11, marginBottom: 4 }}
              formatter={(value) => [
                Number(value ?? 0).toLocaleString(),
                meta.label,
              ]}
            />
            <Area
              type="monotone"
              dataKey={metric}
              stroke={meta.color}
              strokeWidth={2}
              fill={`url(#${meta.gradientId})`}
              activeDot={{ r: 4, strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
