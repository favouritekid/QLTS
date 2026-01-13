/**
 * WelcomeScreen Component
 *
 * First-time setup guide for Admission Configuration
 * Displays when no Phase 1 data exists
 */

"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { GraduationCap, Rocket, CheckCircle2 } from "lucide-react";

// ============================================
// TYPES
// ============================================

interface WelcomeScreenProps {
  onStart: () => void;
}

// ============================================
// COMPONENT
// ============================================

export function WelcomeScreen({ onStart }: WelcomeScreenProps) {
  return (
    <div className="flex items-center justify-center min-h-[80vh] p-6">
      <Card className="max-w-3xl w-full">
        <CardHeader className="text-center pb-4">
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-primary/10 rounded-full">
              <GraduationCap className="h-12 w-12 text-primary" />
            </div>
          </div>
          <CardTitle className="text-3xl">Welcome to Admission Configuration</CardTitle>
          <CardDescription className="text-base mt-2">
            Set up your admission system from scratch in three phases
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-8">
          {/* Phase Overview */}
          <div className="space-y-6">
            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold">
                  1
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Phase 1: Master Data</h3>
                <p className="text-muted-foreground mb-3">
                  Define the foundation of your admission system. This is done once and rarely changes.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Organization units (Departments, Faculties)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Offering types (Regular, Part-time)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Admission methods (High school GPA, National exam, etc.)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Document types (Transcripts, ID cards, etc.)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Subject groups (A00, A01, D01, etc.)
                  </li>
                </ul>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center font-bold">
                  2
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Phase 2: Academic Programs</h3>
                <p className="text-muted-foreground mb-3">
                  Set up your programs and offerings. Add new ones each time you introduce a new program.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Major programs (IT, Business, etc.)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Program offerings (Regular IT, Part-time IT)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Academic year information (Quota, Tuition fees)
                  </li>
                </ul>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-green-100 text-green-600 flex items-center justify-center font-bold">
                  3
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Phase 3: Admission Configuration</h3>
                <p className="text-muted-foreground mb-3">
                  Configure admission paths for each academic year. This is where you bring it all together.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Define admission criteria for each method
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Configure document requirements
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Create admission paths (Method + Criteria + Documents)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Activate paths for student applications
                  </li>
                </ul>
              </div>
            </div>
          </div>

          {/* CTA */}
          <div className="pt-6 border-t">
            <div className="flex flex-col items-center gap-4">
              <p className="text-sm text-muted-foreground text-center max-w-md">
                The system has detected no master data. Let&apos;s get started by setting up Phase 1.
              </p>
              <Button size="lg" onClick={onStart} className="gap-2">
                <Rocket className="h-5 w-5" />
                Start Phase 1 Setup
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
