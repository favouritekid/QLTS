// src/components/leads/LeadInfoTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Building, GraduationCap, MapPin, Calendar, User } from "lucide-react";
import type { Lead } from "@/types/lead.types";

interface LeadInfoTabProps {
  lead: Lead;
}

export function LeadInfoTab({ lead }: LeadInfoTabProps) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* Contact Information */}
      <Card>
        <CardHeader>
          <CardTitle>Contact Information</CardTitle>
          <CardDescription>Basic contact details</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium text-muted-foreground">Full Name</label>
            <p className="text-base font-semibold">{lead.full_name}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Email</label>
            <p className="text-base">{lead.email}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Phone</label>
            <p className="text-base">{lead.phone}</p>
          </div>
          {lead.location && (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Location</label>
              <div className="flex items-center gap-2">
                <MapPin className="h-4 w-4 text-muted-foreground" />
                <p className="text-base">{lead.location}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Academic Information */}
      <Card>
        <CardHeader>
          <CardTitle>Academic Information</CardTitle>
          <CardDescription>Educational background</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {lead.education_level ? (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Education Level</label>
              <div className="flex items-center gap-2">
                <GraduationCap className="h-4 w-4 text-muted-foreground" />
                <p className="text-base capitalize">
                  {lead.education_level.replace(/_/g, " ")}
                </p>
              </div>
            </div>
          ) : (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Education Level</label>
              <p className="text-base text-muted-foreground">Not provided</p>
            </div>
          )}

          {lead.gpa !== null && lead.gpa !== undefined ? (
            <div>
              <label className="text-sm font-medium text-muted-foreground">GPA</label>
              <p className="text-base font-semibold">{lead.gpa.toFixed(2)} / 4.0</p>
            </div>
          ) : (
            <div>
              <label className="text-sm font-medium text-muted-foreground">GPA</label>
              <p className="text-base text-muted-foreground">Not provided</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Lead Metadata */}
      <Card>
        <CardHeader>
          <CardTitle>Lead Metadata</CardTitle>
          <CardDescription>Source and tracking information</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium text-muted-foreground">Source</label>
            <div className="mt-1">
              <Badge variant="outline" className="capitalize">
                {lead.source.replace(/_/g, " ")}
              </Badge>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Lead Score</label>
            <p className="text-base font-semibold">{lead.lead_score}/100</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Created At</label>
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">
                {new Date(lead.created_at).toLocaleString()}
              </p>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Last Updated</label>
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">
                {new Date(lead.updated_at).toLocaleString()}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Assignment Information */}
      <Card>
        <CardHeader>
          <CardTitle>Assignment Information</CardTitle>
          <CardDescription>Officer assignment details</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {lead.assigned_officer_id ? (
            <>
              <div>
                <label className="text-sm font-medium text-muted-foreground">
                  Assigned Officer
                </label>
                <div className="flex items-center gap-2">
                  <User className="h-4 w-4 text-muted-foreground" />
                  <p className="text-base">Officer #{lead.assigned_officer_id}</p>
                </div>
              </div>
              {lead.assigned_at && (
                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Assigned At
                  </label>
                  <div className="flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-muted-foreground" />
                    <p className="text-base">
                      {new Date(lead.assigned_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div>
              <p className="text-muted-foreground">Not assigned to any officer yet</p>
            </div>
          )}

          <div>
            <label className="text-sm font-medium text-muted-foreground">Unit ID</label>
            <div className="flex items-center gap-2">
              <Building className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">Unit #{lead.unit_id}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
