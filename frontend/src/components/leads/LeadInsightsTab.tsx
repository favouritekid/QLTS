// src/components/leads/LeadInsightsTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import {
  TrendingUp,
  AlertTriangle,
  CheckCircle,
  Target,
  Activity,
} from "lucide-react";
import type { LeadInsights } from "@/types/lead.types";

interface LeadInsightsTabProps {
  leadId: number;
  insights?: LeadInsights;
}

export function LeadInsightsTab({ insights }: LeadInsightsTabProps) {
  if (!insights) {
    return (
      <div className="grid gap-6 md:grid-cols-2">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-6 w-32" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-24 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Conversion Probability */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5" />
                Conversion Probability
              </CardTitle>
              <CardDescription>
                AI-predicted likelihood of conversion
              </CardDescription>
            </div>
            <div className="text-3xl font-bold">
              {Math.round(insights.conversion_probability * 100)}%
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Progress value={insights.conversion_probability * 100} className="h-3" />
          <p className="text-sm text-muted-foreground mt-2">
            {insights.conversion_probability >= 0.7
              ? "High probability - Prioritize follow-up"
              : insights.conversion_probability >= 0.4
                ? "Medium probability - Regular follow-up recommended"
                : "Low probability - May need re-qualification"}
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Lead Score Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Lead Score Breakdown
            </CardTitle>
            <CardDescription>
              Factors contributing to lead score
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(insights.lead_score_breakdown).map(([key, value]) => (
              <div key={key} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="capitalize">{key.replace(/_/g, " ")}</span>
                  <span className="font-semibold">{value}/100</span>
                </div>
                <Progress value={value} className="h-2" />
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Engagement Metrics */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Engagement Metrics
            </CardTitle>
            <CardDescription>
              Lead engagement statistics
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Email Opens</span>
              <span className="font-semibold">
                {insights.engagement_metrics.email_opens}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Email Clicks</span>
              <span className="font-semibold">
                {insights.engagement_metrics.email_clicks}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Website Visits</span>
              <span className="font-semibold">
                {insights.engagement_metrics.website_visits}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Form Submissions</span>
              <span className="font-semibold">
                {insights.engagement_metrics.form_submissions}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Last Activity</span>
              <span className="font-semibold">
                {insights.engagement_metrics.last_activity_days} days ago
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recommended Actions */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle className="h-5 w-5" />
            Recommended Actions
          </CardTitle>
          <CardDescription>
            AI-suggested next steps
          </CardDescription>
        </CardHeader>
        <CardContent>
          {insights.recommended_actions.length === 0 ? (
            <p className="text-muted-foreground">No recommendations at this time</p>
          ) : (
            <ul className="space-y-3">
              {insights.recommended_actions.map((action, index) => (
                <li key={index} className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                    <span className="text-xs font-semibold text-primary">
                      {index + 1}
                    </span>
                  </div>
                  <div className="flex-1">
                    <h4 className="font-medium">{action.action}</h4>
                    <p className="text-sm text-muted-foreground">{action.reason}</p>
                    <Badge variant="outline" className="mt-1 capitalize">
                      Priority: {action.priority}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Risk Factors */}
      {insights.risk_factors.length > 0 && (
        <Card className="border-yellow-200 bg-yellow-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-yellow-900">
              <AlertTriangle className="h-5 w-5" />
              Risk Factors
            </CardTitle>
            <CardDescription className="text-yellow-700">
              Potential concerns to address
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {insights.risk_factors.map((risk, index) => (
                <li key={index} className="flex items-start gap-2 text-yellow-900">
                  <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                  <span className="text-sm">{risk}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
