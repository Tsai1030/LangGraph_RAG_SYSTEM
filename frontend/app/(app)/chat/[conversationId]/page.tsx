"use client";

import { useParams } from "next/navigation";

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();

  return (
    <div className="flex-1 flex flex-col items-center justify-center text-gray-400 text-sm">
      <p>對話 ID：{conversationId}</p>
      <p className="mt-2">Chat UI — Phase 5 實作</p>
    </div>
  );
}
