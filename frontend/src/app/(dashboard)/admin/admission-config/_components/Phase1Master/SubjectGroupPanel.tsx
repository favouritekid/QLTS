/**
 * SubjectGroupPanel Component
 *
 * Phase 1.5: Subject & Subject Group Management
 * Comprehensive interface for:
 * - Subject CRUD
 * - Subject Group CRUD
 * - M2M relationship management (assigning subjects to groups)
 */

"use client";

import { useState } from "react";
import { BookOpen, Users } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SubjectTable } from "./SubjectTable";
import { SubjectGroupTable } from "./SubjectGroupTable";
import { SubjectGroupAssignment } from "./SubjectGroupAssignment";

// ============================================
// COMPONENT
// ============================================

export function SubjectGroupPanel() {
  const [activeTab, setActiveTab] = useState("subjects");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Subjects & Subject Groups</h1>
        <p className="text-muted-foreground mt-2">
          Manage subjects (Math, Physics, etc.) and subject groups (A00, A01, D01, etc.)
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="subjects">
            <BookOpen className="h-4 w-4 mr-2" />
            Subjects
          </TabsTrigger>
          <TabsTrigger value="groups">
            <Users className="h-4 w-4 mr-2" />
            Subject Groups
          </TabsTrigger>
          <TabsTrigger value="assignment">
            <Users className="h-4 w-4 mr-2" />
            Group Assignment
          </TabsTrigger>
        </TabsList>

        <TabsContent value="subjects" className="space-y-4">
          <SubjectTable />
        </TabsContent>

        <TabsContent value="groups" className="space-y-4">
          <SubjectGroupTable />
        </TabsContent>

        <TabsContent value="assignment" className="space-y-4">
          <SubjectGroupAssignment />
        </TabsContent>
      </Tabs>
    </div>
  );
}
