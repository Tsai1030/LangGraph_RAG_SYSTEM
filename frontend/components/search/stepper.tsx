import { cn } from "@/lib/utils";
import { Check } from "lucide-react";

export interface StepperProps {
  current: number;
  steps: string[];
}

export function Stepper({ current, steps }: StepperProps) {
  return (
    <ol className="flex items-center gap-2">
      {steps.map((label, i) => {
        const idx = i + 1;
        const isActive = idx === current;
        const isDone = idx < current;
        return (
          <li key={label} className="flex flex-1 items-center gap-2">
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1",
                isDone &&
                  "bg-blue-600 text-white ring-blue-600",
                isActive &&
                  !isDone &&
                  "bg-blue-50 text-blue-700 ring-blue-600",
                !isActive &&
                  !isDone &&
                  "bg-gray-50 text-gray-400 ring-gray-200",
              )}
            >
              {isDone ? <Check className="h-4 w-4" /> : idx}
            </div>
            <span
              className={cn(
                "hidden text-sm sm:inline",
                isActive ? "font-medium text-gray-900" : "text-gray-500",
              )}
            >
              {label}
            </span>
            {i < steps.length - 1 && (
              <div
                className={cn(
                  "h-px flex-1",
                  isDone ? "bg-blue-600" : "bg-gray-200",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
