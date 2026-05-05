import { getAccessToken, useAuthStore } from "@/store/authStore";
import type { FormFile, Source } from "@/types";

async function attemptTokenRefresh(): Promise<string> {
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error("UNAUTHORIZED");
  const data = await res.json();
  const newToken: string = data.access_token;
  useAuthStore.getState().setAccessToken(newToken);
  return newToken;
}

export async function streamChat(
  conversationId: string,
  message: string,
  onText: (text: string) => void,
  onFormLoading: () => void,
  onFormFiles: (files: FormFile[]) => void,
  onSources: (sources: Source[]) => void,
  onDone: () => void,
  signal?: AbortSignal
): Promise<void> {
  let token = getAccessToken();

  // 直連後端，繞過 Next.js rewrites 的 response buffering
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

  const doFetch = (t: string | null) =>
    fetch(`${backendUrl}/api/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(t ? { Authorization: `Bearer ${t}` } : {}),
      },
      body: JSON.stringify({ conversation_id: conversationId, message }),
      signal,
    });

  let response = await doFetch(token);

  // Token 過期 → 嘗試 refresh 一次
  if (response.status === 401) {
    try {
      token = await attemptTokenRefresh();
    } catch {
      throw new Error("UNAUTHORIZED");
    }
    response = await doFetch(token);
  }

  if (response.status === 503) {
    throw new Error("OVERLOADED");
  }

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;

      const event = JSON.parse(raw);
      switch (event.type) {
        case "text":
          onText(event.content);
          break;
        case "form_loading":
          onFormLoading();
          break;
        case "form_files":
          onFormFiles(event.data);
          break;
        case "sources":
          onSources(event.data);
          break;
        case "error":
          // 後端 graph 內部錯誤 → 中斷 stream，由 page.tsx 的 catch 處理顯示
          throw new Error("STREAM_ERROR");
        case "done":
          onDone();
          return;
      }
    }
  }
}
