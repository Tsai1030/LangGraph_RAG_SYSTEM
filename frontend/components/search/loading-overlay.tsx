"use client";

import { useEffect, useState } from "react";

export interface LoadingStep {
  /** Short status label rotated under the SVG. */
  text: string;
  /** Approximate dwell time (ms) before advancing to the next step. */
  durationMs: number;
}

interface Props {
  open: boolean;
  title: string;
  subtitle?: string;
  steps: LoadingStep[];
}

/**
 * macOS-style loading sheet whose centrepiece is a hand-drawn SVG illustration
 * — a document being progressively traced by an invisible pen. Each path uses
 * stroke-dashoffset keyframes so it appears to be drawn from start → end. The
 * whole figure cycles indefinitely (draw → hold → fade → restart).
 *
 * Below the figure: a small status text mirrors what the agent is doing
 * (cycled from `steps`), plus a continuous progress bar.
 */
export function LoadingOverlay(props: Props) {
  if (!props.open) return null;
  return <LoadingOverlayInner {...props} />;
}

function LoadingOverlayInner({ open, title, subtitle, steps }: Props) {
  void open;
  const [statusIndex, setStatusIndex] = useState(0);

  useEffect(() => {
    if (statusIndex >= steps.length - 1) return;
    const id = setTimeout(
      () => setStatusIndex((i) => i + 1),
      steps[statusIndex].durationMs,
    );
    return () => clearTimeout(id);
  }, [statusIndex, steps]);

  const progress =
    steps.length > 0
      ? Math.min(100, ((statusIndex + 1) / steps.length) * 100)
      : 0;
  const currentStatus = steps[statusIndex]?.text ?? "處理中…";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{
        background: "oklch(20% 0.01 250 / 0.40)",
        backdropFilter: "blur(8px) saturate(140%)",
        WebkitBackdropFilter: "blur(8px) saturate(140%)",
      }}
    >
      <div
        className="w-full max-w-[460px] window-in overflow-hidden mx-2"
        style={{
          background: "var(--search-surface-window)",
          borderRadius: "var(--search-radius-window)",
          boxShadow: "var(--search-shadow-window)",
        }}
      >
        {/* Title bar */}
        <div
          className="flex items-center px-4 h-10 border-b"
          style={{
            background: "var(--search-surface-titlebar)",
            backdropFilter: "blur(20px) saturate(180%)",
            WebkitBackdropFilter: "blur(20px) saturate(180%)",
            borderColor: "var(--search-border-subtle)",
          }}
        >
          <span
            className="select-none"
            style={{
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, "Cascadia Mono", monospace',
              fontWeight: 800,
              fontSize: "14px",
              letterSpacing: "0.06em",
              lineHeight: 1,
              color: "var(--search-accent)",
            }}
          >
            BES
          </span>
          <div className="flex-1 text-center">
            <span className="text-[12px] font-medium" style={{ color: "var(--search-text-secondary)" }}>
              處理中
            </span>
          </div>
          <div className="w-[68px]" />
        </div>

        {/* Body */}
        <div className="px-5 sm:px-7 pt-5 sm:pt-6 pb-6 sm:pb-7 flex flex-col items-center">
          {/* SVG canvas — generates the artwork by tracing strokes */}
          <DrawingCanvas />

          {/* Title */}
          <h2
            className="mt-5 text-[15px] font-semibold leading-tight text-center"
            style={{ color: "var(--search-text-primary)" }}
          >
            {title}
          </h2>
          {subtitle && (
            <p
              className="mt-1 text-[12px] text-center"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              {subtitle}
            </p>
          )}

          {/* Status line */}
          <div className="mt-5 flex items-center gap-2 text-[12px] font-mono px-3 py-1.5 rounded-md"
            style={{
              background: "var(--search-surface-hover)",
              color: "var(--search-text-secondary)",
            }}
          >
            <span
              className="block w-1.5 h-1.5 rounded-full"
              style={{
                background: "var(--search-accent)",
                animation: "accent-pulse 1.4s ease-in-out infinite",
              }}
            />
            <span className="truncate max-w-[280px]">{currentStatus}</span>
          </div>

          {/* Progress */}
          <div className="mt-5 w-full">
            <div
              className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wider"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              <span>進度</span>
              <span className="tabular-nums">{Math.round(progress)}%</span>
            </div>
            <div
              className="mt-1.5 h-1 overflow-hidden rounded-full"
              style={{ background: "var(--search-surface-hover)" }}
            >
              <div
                className="h-full rounded-full transition-[width] duration-500 ease-out"
                style={{
                  width: `${progress}%`,
                  background:
                    "linear-gradient(90deg, var(--search-accent), oklch(70% 0.16 145))",
                }}
              />
            </div>
          </div>

          <p
            className="mt-4 text-[11px] leading-relaxed text-center"
            style={{ color: "var(--search-text-tertiary)" }}
          >
            視 OpenAI 回應與雲端冷啟動約需 2–3 分鐘，請耐心等候。
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   The "drawn document" illustration.

   Each path:
     - Has a `--len` CSS var equal to its `pathLength="100"` attribute, so
       stroke-dashoffset can reliably animate from full → 0 regardless of
       actual path length.
     - Uses the same animation but staggered via `animation-delay`, so the
       paths draw one after another, hold together, then all fade and the
       cycle restarts.

   Total cycle: 4.5 seconds.
   ────────────────────────────────────────────────────────────── */

const CYCLE = "4.5s";

function DrawingCanvas() {
  return (
    <div
      className="w-full flex items-center justify-center py-4"
      style={{
        background:
          "radial-gradient(ellipse at center, oklch(98% 0.005 250) 0%, oklch(95% 0.005 250) 100%)",
        borderRadius: "var(--search-radius-card)",
        boxShadow: "inset 0 0 0 0.5px oklch(0% 0 0 / 0.05)",
      }}
    >
      <svg
        viewBox="0 0 200 160"
        width="200"
        height="160"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ color: "var(--search-accent)" }}
      >
        {/* Document outer rectangle (with folded corner) */}
        <DrawPath
          d="M 50 30 L 130 30 L 150 50 L 150 140 L 50 140 Z"
          delay={0}
        />

        {/* Folded corner */}
        <DrawPath
          d="M 130 30 L 130 50 L 150 50"
          delay={350}
          color="oklch(70% 0.20 305)"
        />

        {/* Title underline (a thicker / more prominent first text line) */}
        <DrawPath
          d="M 65 65 L 125 65"
          delay={700}
          color="oklch(70% 0.20 305)"
          width={3}
        />

        {/* Body text lines */}
        <DrawPath d="M 65 80 L 135 80"  delay={950}  />
        <DrawPath d="M 65 92 L 130 92"  delay={1100} />
        <DrawPath d="M 65 104 L 138 104" delay={1250} />

        {/* Section divider */}
        <DrawPath
          d="M 65 116 L 100 116"
          delay={1400}
          color="oklch(72% 0.16 50)"
        />

        {/* Last short line */}
        <DrawPath d="M 65 128 L 120 128" delay={1550} />

        {/* Sparkles "✦" — one star at top-right of the doc */}
        <DrawPath
          d="M 165 22 L 165 42 M 155 32 L 175 32"
          delay={1750}
          color="oklch(72% 0.16 50)"
          width={2.2}
        />
        <DrawPath
          d="M 30 110 L 30 122 M 24 116 L 36 116"
          delay={1900}
          color="oklch(72% 0.15 145)"
          width={2.2}
        />
      </svg>
    </div>
  );
}

/**
 * Single SVG path that draws itself via stroke-dashoffset.
 *
 * Why pathLength="100" trick: it normalises the path length so we can use
 * `--len: 100` everywhere without measuring real path lengths via JS at
 * runtime. The stroke-dashoffset interpolates 100 → 0.
 */
function DrawPath({
  d,
  delay,
  color,
  width = 2,
}: {
  d: string;
  delay: number;
  color?: string;
  width?: number;
}) {
  return (
    <path
      d={d}
      pathLength={100}
      stroke={color ?? "var(--search-accent)"}
      strokeWidth={width}
      strokeDasharray={100}
      strokeDashoffset={100}
      style={{
        // stagger via delay; total cycle stays in sync across all paths
        animation: `svg-draw-cycle ${CYCLE} ${delay}ms cubic-bezier(0.65, 0, 0.35, 1) infinite both`,
        // CSS variable consumed by the keyframes
        ["--len" as string]: "100",
      }}
    />
  );
}
