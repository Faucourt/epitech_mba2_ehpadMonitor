import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import type { WSMessage, Resident, Alert } from '../types';

const BACKEND_WS = import.meta.env.VITE_WS_URL || `ws://${window.location.hostname}:8001/ws`;

interface WSContextValue {
  residents: Record<string, Resident>;
  activeAlerts: Record<string, Alert>;
  connected: boolean;
}

const WSContext = createContext<WSContextValue>({
  residents: {},
  activeAlerts: {},
  connected: false,
});

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [residents, setResidents] = useState<Record<string, Resident>>({});
  const [activeAlerts, setActiveAlerts] = useState<Record<string, Alert>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    const ws = new WebSocket(BACKEND_WS);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      reconnectTimer.current = setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();

    ws.onmessage = (ev) => {
      try {
        const msg: WSMessage = JSON.parse(ev.data);
        if (msg.type === 'summary') {
          setResidents(() => {
            const m: Record<string, Resident> = {};
            msg.residents.forEach(r => { m[r.id] = r; });
            return m;
          });
          setActiveAlerts(() => {
            const m: Record<string, Alert> = {};
            msg.active_alerts.forEach(a => { m[a.resident_id] = a; });
            return m;
          });
        } else if (msg.type === 'resident_update') {
          setResidents(prev => ({ ...prev, [msg.resident.id]: msg.resident }));
        } else if (msg.type === 'alert') {
          const a = msg.alert;
          if (a.resolved) {
            setActiveAlerts(prev => {
              const next = { ...prev };
              delete next[a.resident_id];
              return next;
            });
          } else {
            setActiveAlerts(prev => ({ ...prev, [a.resident_id]: a }));
          }
        }
      } catch {
        // ignore malformed messages
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return (
    <WSContext.Provider value={{ residents, activeAlerts, connected }}>
      {children}
    </WSContext.Provider>
  );
}

export function useWS() {
  return useContext(WSContext);
}
