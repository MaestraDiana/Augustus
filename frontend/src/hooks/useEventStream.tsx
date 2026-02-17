import { createContext, useContext, useEffect, useRef, useCallback, ReactNode } from 'react';

/**
 * Server-Sent Events hook for real-time data-change notifications.
 *
 * Maintains a single global EventSource connection to /api/events.
 * Components subscribe to specific event types and receive callbacks
 * when matching events arrive.
 */

export interface DataChangeEvent {
  type: string;      // flag_resolved, proposal_resolved, basin_updated, etc.
  agent_id: string;
  payload: Record<string, unknown>;
}

type EventCallback = (event: DataChangeEvent) => void;

interface EventStreamContextValue {
  /** Subscribe to events. Returns an unsubscribe function. */
  subscribe: (callback: EventCallback) => () => void;
}

const EventStreamContext = createContext<EventStreamContextValue>({
  subscribe: () => () => {},
});

export function EventStreamProvider({ children }: { children: ReactNode }) {
  const callbacksRef = useRef<Set<EventCallback>>(new Set());
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    // Close existing connection if any
    if (sourceRef.current) {
      sourceRef.current.close();
    }

    const source = new EventSource('/api/events');
    sourceRef.current = source;

    source.addEventListener('update', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as DataChangeEvent;
        callbacksRef.current.forEach(cb => {
          try {
            cb(data);
          } catch (err) {
            console.error('Event callback error:', err);
          }
        });
      } catch {
        // Ignore malformed events
      }
    });

    source.onerror = () => {
      // EventSource will auto-reconnect, but if it gives up, we retry
      if (source.readyState === EventSource.CLOSED) {
        source.close();
        sourceRef.current = null;
        // Exponential backoff capped at 10s
        if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = setTimeout(connect, 5000);
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [connect]);

  const subscribe = useCallback((callback: EventCallback) => {
    callbacksRef.current.add(callback);
    return () => {
      callbacksRef.current.delete(callback);
    };
  }, []);

  return (
    <EventStreamContext.Provider value={{ subscribe }}>
      {children}
    </EventStreamContext.Provider>
  );
}

/**
 * Subscribe to real-time data-change events.
 *
 * @param eventTypes - Event types to listen for (e.g. ['flag_resolved', 'flag_created'])
 * @param callback - Called when a matching event arrives
 * @param agentId - Optional: only receive events for this agent
 */
export function useDataEvents(
  eventTypes: string[],
  callback: (event: DataChangeEvent) => void,
  agentId?: string,
) {
  const { subscribe } = useContext(EventStreamContext);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const typesKey = eventTypes.join(',');

  useEffect(() => {
    const handler: EventCallback = (event) => {
      if (!eventTypes.includes(event.type)) return;
      if (agentId && event.agent_id && event.agent_id !== agentId) return;
      callbackRef.current(event);
    };
    return subscribe(handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subscribe, typesKey, agentId]);
}
