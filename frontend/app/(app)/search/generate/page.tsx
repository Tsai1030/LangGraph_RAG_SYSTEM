"use client";

import { GenerateView } from "@/components/search/generate-view";

/**
 * /search/generate — the 鋼筋採購週會 wizard.
 *
 * GenerateView is self-contained (holds its own step / form / mutation
 * state). Wrapping it in a small div with macOS-style padding so it
 * sits cleanly inside the main content area provided by (app)/layout.
 */
export default function SearchGeneratePage() {
  return (
    <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6 sm:py-10">
      <GenerateView />
    </div>
  );
}
