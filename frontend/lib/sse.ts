import { getAccessToken } from "@/store/authStore";
import type { FormData, Source } from "@/types";

export async function streamChat(
  conversationId: string,
  message: string,
  onText: (text: string) => void,
  onForm: (formData: FormData) => void,
  onSources: (sources: Source[]) => void,
  onDone: () => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getAccessToken();

  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ conversation_id: conversationId, message }),
    signal,
  });

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
        case "form":
          onForm(event.data);
          break;
        case "sources":
          onSources(event.data);
          break;
        case "done":
          onDone();
          return;
      }
    }
  }
}
