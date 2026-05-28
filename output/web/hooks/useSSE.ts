"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { LogEntry } from "@/lib/types";

export function useSSE(url: string, maxLines = 2000) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [totalReceived, setTotalReceived] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close();

    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.addEventListener("log", (event: MessageEvent) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        setTotalReceived((c) => c + 1);
        setLogs((prev) => {
          const next = [...prev.slice(-(maxLines - 1)), entry];
          return next;
        });
      } catch { /* ignore malformed */ }
    });

    es.onmessage = (event: MessageEvent) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        setTotalReceived((c) => c + 1);
        setLogs((prev) => [...prev.slice(-(maxLines - 1)), entry]);
      } catch { /* ignore */ }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      reconnectTimer.current = setTimeout(connect, 3000);
    };
  }, [url, maxLines]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  const clear = useCallback(() => {
    setLogs([]);
    setTotalReceived(0);
  }, []);

  return { logs, connected, totalReceived, clear };
}
