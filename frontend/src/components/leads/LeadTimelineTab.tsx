// src/components/leads/LeadTimelineTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Clock, User, FileText } from "lucide-react";
import type { TimelineItem } from "@/types/lead.types";

interface LeadTimelineTabProps {
  leadId: number;
  timeline?: TimelineItem[];
}

const eventTypeColors: Record<string, string> = {
  created: "bg-blue-100 text-blue-800",
  updated: "bg-yellow-100 text-yellow-800",
  assigned: "bg-green-100 text-green-800",
  status_changed: "bg-purple-100 text-purple-800",
  consultation_added: "bg-pink-100 text-pink-800",
  note_added: "bg-gray-100 text-gray-800",
};

export function LeadTimelineTab({ timeline }: LeadTimelineTabProps) {
  if (!timeline) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Timeline</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
        <CardDescription>
          Complete history of activities for this lead
        </CardDescription>
      </CardHeader>
      <CardContent>
        {timeline.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No timeline events recorded yet
          </div>
        ) : (
          <div className="space-y-4">
            {timeline.map((event, index) => (
              <div key={event.id || index} className="flex gap-4 relative">
                {/* Timeline line */}
                {index !== timeline.length - 1 && (
                  <div className="absolute left-4 top-8 bottom-0 w-0.5 bg-border" />
                )}

                {/* Timeline dot */}
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center z-10">
                  {(event.event_type || event.type) === "consultation_added" ? (
                    <FileText className="h-4 w-4 text-primary" />
                  ) : (event.event_type || event.type) === "assigned" ? (
                    <User className="h-4 w-4 text-primary" />
                  ) : (
                    <Clock className="h-4 w-4 text-primary" />
                  )}
                </div>

                {/* Event content */}
                <div className="flex-1 pb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge
                      variant="outline"
                      className={eventTypeColors[event.event_type || event.type] || eventTypeColors.note_added}
                    >
                      {(event.event_type || event.type).replace(/_/g, " ")}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {new Date(event.created_at || event.timestamp).toLocaleString()}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{event.description}</p>
                  {event.actor_id && (
                    <p className="text-xs text-muted-foreground mt-1">
                      By: User #{event.actor_id}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
