"use client";

import React, { useEffect, useRef } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { formatTimestamp } from "../lib/format";
import type { AgentEvent } from "../types";
import { EventIcon } from "./EventIcon";
import { EventInspector } from "./EventInspector";
import { StatusBadge } from "./StatusBadge";

interface EventFeedProps {
  events: AgentEvent[];
  expandedEvents: Record<string, boolean>;
  onToggleEvent: (eventId: string) => void;
}

/** "Live Execution Feed": chronological event cards that expand into the inspector. */
export function EventFeed({ events, expandedEvents, onToggleEvent }: EventFeedProps) {
  const eventFeedEndRef = useRef<HTMLDivElement>(null);
  const lastScrolledEvents = useRef(events);

  // Auto-scroll to the bottom when the event list changes. Mounting the feed
  // (e.g. switching back from the memories tab) does not scroll by itself.
  useEffect(() => {
    if (lastScrolledEvents.current === events) return;
    lastScrolledEvents.current = events;
    eventFeedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <section className="flex-1 flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
      <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
        <h3 className="font-bold text-xs uppercase tracking-wider text-white">
          Live Execution Feed
        </h3>
        <span className="text-[10px] text-muted-foreground font-mono">
          {events.length} Events Received
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {events.map((event) => {
          const isExpanded = !!expandedEvents[event.event_id];
          return (
            <div
              key={event.event_id}
              className="border border-border/80 bg-secondary/10 rounded-xl overflow-hidden"
            >
              <div
                onClick={() => onToggleEvent(event.event_id)}
                className="p-3 flex items-center justify-between cursor-pointer hover:bg-secondary/20 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="p-1.5 rounded-lg bg-secondary">
                    <EventIcon type={event.event_type} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-xs text-white">
                        {event.agent_name || "System"}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono bg-secondary px-1.5 py-0.5 rounded">
                        {event.event_type}
                      </span>
                    </div>
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {formatTimestamp(event.timestamp)}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={event.status} />
                  {isExpanded ? (
                    <ChevronUp className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  )}
                </div>
              </div>

              {/* Expandable Details Drawer */}
              {isExpanded && <EventInspector event={event} allEvents={events} />}
            </div>
          );
        })}
        <div ref={eventFeedEndRef} />
      </div>
    </section>
  );
}
