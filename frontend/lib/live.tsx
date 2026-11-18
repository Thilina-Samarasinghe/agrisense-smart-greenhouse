"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { get, WS_URL, type AppConfig, type LiveState } from "./api";

type LiveContext = {
  live: LiveState | null;
  config: AppConfig | null;
  connected: boolean;
  error: string | null;
};

const Ctx = createContext<LiveContext>({ live: null, config: null, connected: false, error: null });

/** One WebSocket for the whole app, reconnecting with back-off; static config loaded once. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [live, setLive] = useState<LiveState | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const runId = useRef<number | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 500;
    let stopped = false;

    const loadConfig = () =>
      get<AppConfig>("/api/config")
        .then((c) => {
          setConfig(c);
          setError(null);
        })
        .catch(() => setError("Backend unreachable"));

    const connect = () => {
      ws = new WebSocket(`${WS_URL}/ws/live`);
      ws.onopen = () => {
        setConnected(true);
        setError(null);
        delay = 500;
        loadConfig();
      };
      ws.onmessage = (ev) => {
        const state = JSON.parse(ev.data) as LiveState;
        if (runId.current !== null && runId.current !== state.run_id) loadConfig();
        runId.current = state.run_id;
        setLive(state);
      };
      ws.onclose = () => {
        setConnected(false);
        if (stopped) return;
        setError("Backend unreachable: start it with uvicorn (see README)");
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 8000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return <Ctx.Provider value={{ live, config, connected, error }}>{children}</Ctx.Provider>;
}

export const useLive = () => useContext(Ctx);

/** Re-run `load` every `ms` (and when deps change), keeping the previous data while refetching. */
export function usePolling<T>(load: () => Promise<T>, ms: number, deps: unknown[]): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    const run = () =>
      load()
        .then((d) => alive && setData(d))
        .catch(() => undefined);
    run();
    const id = setInterval(run, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}
