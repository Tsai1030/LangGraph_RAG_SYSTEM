"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";

export default function NewPage() {
  const router = useRouter();

  useEffect(() => {
    const create = async () => {
      try {
        const { data } = await api.post("/conversations", {});
        router.replace(`/chat/${data.id}`);
      } catch {
        router.replace("/login");
      }
    };
    create();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
      建立新對話中...
    </div>
  );
}
