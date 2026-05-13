import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

// Simple fetch wrapper (no swr dependency)
function useFetch<T>(url: string, interval?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}${url}`);
      if (r.ok) {
        const json = await r.json();
        setData(json);
      }
    } catch (e) {
      setError(e as Error);
    }
  }, [url]);

  useEffect(() => {
    fetchData();
    if (interval) {
      const id = setInterval(fetchData, interval);
      return () => clearInterval(id);
    }
  }, [fetchData, interval]);

  return { data, error, refresh: fetchData };
}

export function useAccount() {
  return useFetch('/api/account', 5000);
}

export function usePositions() {
  return useFetch('/api/positions', 5000);
}

export function useTrades(params?: Record<string, string>) {
  const query = params ? '?' + new URLSearchParams(params) : '';
  return useFetch(`/api/trades${query}`, 10000);
}

export function usePerformance() {
  return useFetch('/api/performance', 30000);
}

export function useRiskMetrics() {
  return useFetch('/api/risk-metrics', 5000);
}

export function useStatus() {
  return useFetch('/api/status', 5000);
}

export function useStrategies() {
  return useFetch('/api/strategies');
}

export function useBacktestResults() {
  return useFetch('/api/backtest/results');
}

export function useWebSocket(onMessage: (data: any) => void) {
  useEffect(() => {
    const wsUrl = `ws://${API_BASE.replace(/^https?:\/\//, '').replace(/\/+$/, '')}/ws`;
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (event) => {
      try { onMessage(JSON.parse(event.data)); } catch { /* ignore */ }
    };
    return () => ws.close();
  }, [onMessage]);
}
