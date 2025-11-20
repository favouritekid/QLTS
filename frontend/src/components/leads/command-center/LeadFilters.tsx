// src/components/leads/command-center/LeadFilters.tsx
"use client";

import React from "react";
import { Search, X, RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LeadStatus, LeadSource } from "@/types/lead.types";
import type { ProgramOffering } from "@/types/organization.types";

interface LeadFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilters: LeadStatus[];
  onStatusChange: (statuses: LeadStatus[]) => void;
  sourceFilter: string;
  onSourceChange: (source: string) => void;
  scoreRange: [number, number];
  onScoreRangeChange: (range: [number, number]) => void;
  offeringFilter: string;
  onOfferingChange: (offeringId: string) => void;
  offerings: ProgramOffering[];
  onReset: () => void;
}

const STATUS_OPTIONS: { value: LeadStatus; label: string; color: string }[] = [
  { value: "new", label: "New", color: "bg-blue-500" },
  { value: "assigned", label: "Assigned", color: "bg-purple-500" },
  { value: "contacted", label: "Contacted", color: "bg-cyan-500" },
  { value: "qualified", label: "Qualified", color: "bg-emerald-500" },
  { value: "unqualified", label: "Unqualified", color: "bg-gray-500" },
  { value: "converted", label: "Converted", color: "bg-green-500" },
  { value: "rejected", label: "Rejected", color: "bg-red-500" },
];

const SOURCE_OPTIONS: { value: LeadSource; label: string }[] = [
  { value: "website", label: "Website" },
  { value: "referral", label: "Referral" },
  { value: "social_media", label: "Social Media" },
  { value: "walk_in", label: "Walk-in" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "event", label: "Event" },
  { value: "other", label: "Other" },
];

export const LeadFilters = React.memo(function LeadFilters({
  search,
  onSearchChange,
  statusFilters,
  onStatusChange,
  sourceFilter,
  onSourceChange,
  scoreRange,
  onScoreRangeChange,
  offeringFilter,
  onOfferingChange,
  offerings,
  onReset,
}: LeadFiltersProps) {
  const handleStatusToggle = (status: LeadStatus) => {
    if (statusFilters.includes(status)) {
      onStatusChange(statusFilters.filter((s) => s !== status));
    } else {
      onStatusChange([...statusFilters, status]);
    }
  };

  const hasActiveFilters =
    search ||
    statusFilters.length > 0 ||
    sourceFilter !== "all" ||
    scoreRange[0] > 0 ||
    scoreRange[1] < 100 ||
    offeringFilter !== "all";

  return (
    <div className="w-[280px] shrink-0 border-r bg-card">
      <div className="sticky top-0 h-[calc(100vh-200px)] overflow-y-auto p-4 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Filters</h3>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onReset}
              className="h-7 px-2 text-xs"
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Reset
            </Button>
          )}
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search name, phone, email..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-8 pr-8"
          />
          {search && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Filter Accordions */}
        <Accordion type="multiple" defaultValue={["status", "source"]} className="space-y-2">
          {/* Status Filter */}
          <AccordionItem value="status" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Status
              {statusFilters.length > 0 && (
                <span className="ml-auto mr-2 text-xs bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">
                  {statusFilters.length}
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <div className="space-y-2">
                {STATUS_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`status-${option.value}`}
                      checked={statusFilters.includes(option.value)}
                      onCheckedChange={() => handleStatusToggle(option.value)}
                    />
                    <Label
                      htmlFor={`status-${option.value}`}
                      className="text-sm font-normal cursor-pointer flex items-center gap-2"
                    >
                      <span className={`w-2 h-2 rounded-full ${option.color}`} />
                      {option.label}
                    </Label>
                  </div>
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Source Filter */}
          <AccordionItem value="source" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Source
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <Select value={sourceFilter} onValueChange={onSourceChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="All sources" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sources</SelectItem>
                  {SOURCE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </AccordionContent>
          </AccordionItem>

          {/* Lead Score Filter */}
          <AccordionItem value="score" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Lead Score
            </AccordionTrigger>
            <AccordionContent className="pb-3 pt-2">
              <div className="space-y-4">
                <Slider
                  value={scoreRange}
                  onValueChange={(value) => onScoreRangeChange(value as [number, number])}
                  max={100}
                  min={0}
                  step={5}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{scoreRange[0]}</span>
                  <span>{scoreRange[1]}</span>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Offering Filter */}
          <AccordionItem value="offering" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Program Offering
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <Select value={offeringFilter} onValueChange={onOfferingChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="All offerings" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Offerings</SelectItem>
                  {offerings.map((offering) => (
                    <SelectItem key={offering.id} value={offering.id.toString()}>
                      {offering.program?.name || offering.offering_type}
                      {offering.program && ` (${offering.offering_type})`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  );
});
