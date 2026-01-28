// src/components/officer/ActionableLists.tsx
"use client";

import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { TrendingUp, AlertTriangle, Calendar, ArrowRight, Mail } from "lucide-react";

interface HighScoreLead {
  id: number;
  full_name: string;
  email: string;
  lead_score: number;
  status: string;
  created_at: string;
}

interface StaleLead {
  id: number;
  full_name: string;
  email: string;
  last_updated: string;
  days_stale: number;
}

interface UpcomingConsultation {
  id: number;
  lead_id: number;
  lead_name: string;
  consultation_date: string;
  method: string;
  notes: string | null;
}

interface ActionableListsProps {
  lists: {
    high_score: HighScoreLead[];
    stale: StaleLead[];
    upcoming: UpcomingConsultation[];
  };
}

export function ActionableLists({ lists }: ActionableListsProps) {
  return (
    <div className="grid gap-6 md:grid-cols-3">
      {/* High Score Leads */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-success-600" />
            <CardTitle>High-Value Leads</CardTitle>
          </div>
          <CardDescription>
            Top {lists.high_score.length} leads by score - Focus here first
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[300px]">
            {lists.high_score.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No high-score leads at the moment
              </p>
            ) : (
              <div className="space-y-4">
                {lists.high_score.map((lead) => (
                  <div
                    key={lead.id}
                    className="flex items-start justify-between border-b pb-3 last:border-0"
                  >
                    <div className="space-y-1 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-sm">{lead.full_name}</p>
                        <Badge variant="outline" className="text-xs">
                          {lead.lead_score}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Mail className="h-3 w-3" />
                        {lead.email}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Created{" "}
                        {new Date(lead.created_at).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })}
                      </p>
                    </div>
                    <Link href={`/leads/${lead.id}`}>
                      <Button size="sm" variant="ghost">
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Stale Leads */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-warning-600" />
            <CardTitle>Stale Leads</CardTitle>
          </div>
          <CardDescription>
            {lists.stale.length} leads need attention - No activity in 3+ days
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[300px]">
            {lists.stale.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                Great! No stale leads
              </p>
            ) : (
              <div className="space-y-4">
                {lists.stale.map((lead) => (
                  <div
                    key={lead.id}
                    className="flex items-start justify-between border-b pb-3 last:border-0"
                  >
                    <div className="space-y-1 flex-1">
                      <p className="font-medium text-sm">{lead.full_name}</p>
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Mail className="h-3 w-3" />
                        {lead.email}
                      </div>
                      <Badge variant="destructive" className="text-xs">
                        {lead.days_stale} days stale
                      </Badge>
                    </div>
                    <Link href={`/leads/${lead.id}`}>
                      <Button size="sm" variant="ghost">
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Upcoming Consultations */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-info-600" />
            <CardTitle>Today&apos;s Schedule</CardTitle>
          </div>
          <CardDescription>
            {lists.upcoming.length} consultation{lists.upcoming.length !== 1 ? "s" : ""} scheduled
            for today
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[300px]">
            {lists.upcoming.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No consultations scheduled today
              </p>
            ) : (
              <div className="space-y-4">
                {lists.upcoming.map((consult) => (
                  <div
                    key={consult.id}
                    className="flex items-start justify-between border-b pb-3 last:border-0"
                  >
                    <div className="space-y-1 flex-1">
                      <p className="font-medium text-sm">{consult.lead_name}</p>
                      <div className="flex items-center gap-2 text-xs">
                        <Badge variant="outline">{consult.method}</Badge>
                        <span className="text-muted-foreground">
                          {new Date(consult.consultation_date).toLocaleTimeString("en-US", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                      {consult.notes && (
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {consult.notes}
                        </p>
                      )}
                    </div>
                    <Link href={`/leads/${consult.lead_id}`}>
                      <Button size="sm" variant="ghost">
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
