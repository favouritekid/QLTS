// src/components/officer/dashboard/MyLeadsQuickAccess.tsx
/**
 * My Leads Quick Access - Mini leads table with filters
 * Shows officer's priority leads with quick actions
 */

"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Users,
  ArrowRight,
  Flame,
  AlertTriangle,
  Sparkles,
  Phone,
  Calendar,
  ExternalLink,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { vi } from "date-fns/locale";

interface LeadPreview {
  id: number;
  name: string;
  lead_score: number;
  stage_name?: string;
  last_contact_at?: string;
  is_hot: boolean;
  is_overdue: boolean;
  is_new: boolean;
}

interface MyLeadsQuickAccessProps {
  leads: LeadPreview[];
  totalCount: number;
  onCall?: (leadId: number) => void;
  onSchedule?: (leadId: number) => void;
}

type FilterType = "all" | "hot" | "overdue" | "new";

const filterConfig = {
  all: { label: "Tất cả", icon: null },
  hot: { label: "Hot", icon: Flame, color: "text-red-500" },
  overdue: { label: "Quá hạn", icon: AlertTriangle, color: "text-amber-500" },
  new: { label: "Mới", icon: Sparkles, color: "text-green-500" },
};

export function MyLeadsQuickAccess({
  leads,
  totalCount,
  onCall,
  onSchedule,
}: MyLeadsQuickAccessProps) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [search, setSearch] = useState("");

  const filteredLeads = useMemo(() => {
    return leads.filter((lead) => {
      // Apply filter
      if (filter === "hot" && !lead.is_hot) return false;
      if (filter === "overdue" && !lead.is_overdue) return false;
      if (filter === "new" && !lead.is_new) return false;

      // Apply search
      if (search && !lead.name.toLowerCase().includes(search.toLowerCase())) {
        return false;
      }

      return true;
    });
  }, [leads, filter, search]);

  const getScoreBadgeVariant = (score: number) => {
    if (score >= 80) return "destructive";
    if (score >= 60) return "default";
    return "secondary";
  };

  return (
    <Card className="col-span-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <Users className="h-5 w-5 text-blue-500" />
            Leads của tôi
            <Badge variant="secondary">{totalCount}</Badge>
          </CardTitle>
          <Button variant="outline" size="sm" asChild>
            <Link href="/leads">
              Xem tất cả <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mt-3">
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
            {(Object.keys(filterConfig) as FilterType[]).map((key) => {
              const config = filterConfig[key];
              const Icon = config.icon;
              return (
                <Button
                  key={key}
                  variant="ghost"
                  size="sm"
                  onClick={() => setFilter(key)}
                  className={cn(
                    "h-7 px-2.5 text-xs font-medium gap-1",
                    filter === key
                      ? "bg-background shadow-sm"
                      : "hover:bg-background/50"
                  )}
                >
                  {Icon && <Icon className={cn("h-3.5 w-3.5", config.color)} />}
                  {config.label}
                </Button>
              );
            })}
          </div>

          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Tìm lead..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 pl-8 text-sm"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {filteredLeads.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Users className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">
              Không tìm thấy leads
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[280px]">
            <div className="space-y-2">
              {filteredLeads.slice(0, 10).map((lead) => (
                <div
                  key={lead.id}
                  className="flex items-center gap-3 p-3 rounded-lg border bg-card hover:bg-muted/50 transition-colors group"
                >
                  {/* Name & Indicators */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/leads/${lead.id}`}
                        className="font-medium text-sm hover:underline truncate"
                      >
                        {lead.name}
                      </Link>
                      {lead.is_hot && (
                        <Flame className="h-4 w-4 text-red-500 flex-shrink-0" />
                      )}
                      {lead.is_overdue && (
                        <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
                      )}
                      {lead.is_new && (
                        <Sparkles className="h-4 w-4 text-green-500 flex-shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      {lead.stage_name && <span>{lead.stage_name}</span>}
                      {lead.stage_name && lead.last_contact_at && <span>•</span>}
                      {/* Fix: Validate date before formatting to prevent runtime errors */}
                      {lead.last_contact_at && !isNaN(new Date(lead.last_contact_at).getTime()) && (
                        <span>
                          {formatDistanceToNow(new Date(lead.last_contact_at), {
                            addSuffix: true,
                            locale: vi,
                          })}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Score */}
                  <Badge
                    variant={getScoreBadgeVariant(lead.lead_score)}
                    className="font-mono text-xs"
                  >
                    {lead.lead_score}
                  </Badge>

                  {/* Quick Actions */}
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      onClick={() => onCall?.(lead.id)}
                    >
                      <Phone className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      onClick={() => onSchedule?.(lead.id)}
                    >
                      <Calendar className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      asChild
                    >
                      <Link href={`/leads/${lead.id}`}>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Link>
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}

        {/* Footer - Fix: Show accurate count based on filtered results */}
        {filteredLeads.length > 0 && (
          <div className="mt-3 pt-3 border-t text-xs text-muted-foreground text-center">
            Hiển thị {Math.min(filteredLeads.length, 10)} / {leads.length} leads
            {leads.length < totalCount && (
              <span className="text-muted-foreground/70"> (tổng: {totalCount})</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
