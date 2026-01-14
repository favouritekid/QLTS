/**
 * SubjectGroupAssignment Component
 *
 * M2M interface for assigning subjects to groups
 * Allows adding/removing subjects and ordering them within groups
 */

"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, X } from "lucide-react";
import {
  useSubjects,
  useSubjectGroups,
  useAddSubjectToGroup,
  useRemoveSubjectFromGroup,
} from "@/hooks/admissions/useMasterData";
import type { Subject, SubjectGroup, SubjectInGroup } from "../shared/types";

// ============================================
// COMPONENT
// ============================================

export function SubjectGroupAssignment() {
  const { data: subjects = [], isLoading: loadingSubjects } = useSubjects();
  const { data: groups = [], isLoading: loadingGroups } = useSubjectGroups();
  const addMutation = useAddSubjectToGroup();
  const removeMutation = useRemoveSubjectFromGroup();

  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [selectedSubjectId, setSelectedSubjectId] = useState<string>("");

  const selectedGroup = groups.find((g: SubjectGroup) => g.id === selectedGroupId);

  const handleAddSubject = async () => {
    if (!selectedGroupId || !selectedSubjectId) return;

    const subjectId = parseInt(selectedSubjectId);
    const position = (selectedGroup?.subjects?.length || 0) + 1;

    await addMutation.mutateAsync({
      groupId: selectedGroupId,
      subjectId,
      position,
    });

    setSelectedSubjectId("");
  };

  const handleRemoveSubject = async (subjectId: number) => {
    if (!selectedGroupId) return;

    await removeMutation.mutateAsync({
      groupId: selectedGroupId,
      subjectId,
    });
  };

  // Get subjects not in current group
  const availableSubjects = subjects.filter((subject: Subject) => {
    if (!selectedGroup?.subjects) return true;
    return !selectedGroup.subjects.some((s: SubjectInGroup) => s.code === subject.code);
  });

  if (loadingSubjects || loadingGroups) {
    return (
      <Card>
        <CardContent className="py-12">
          <p className="text-center text-muted-foreground">Đang tải...</p>
        </CardContent>
      </Card>
    );
  }

  if (groups.length === 0) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="text-center">
            <p className="text-muted-foreground mb-4">
              Chưa có tổ hợp nào. Hãy tạo tổ hợp mới ở tab &quot;Tổ hợp môn&quot; trước.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Chọn Tổ hợp môn</CardTitle>
          <CardDescription>
            Chọn tổ hợp môn để quản lý danh sách môn học
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Select
            value={selectedGroupId?.toString() || ""}
            onValueChange={(value) => setSelectedGroupId(parseInt(value))}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Chọn tổ hợp môn..." />
            </SelectTrigger>
            <SelectContent>
              {groups.map((group: SubjectGroup) => (
                <SelectItem key={group.id} value={group.id.toString()}>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{group.code}</span>
                    <span className="text-muted-foreground">- {group.name}</span>
                    {group.subjects && group.subjects.length > 0 && (
                      <Badge variant="secondary" className="ml-2">
                        {group.subjects.length} môn
                      </Badge>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {selectedGroup && (
        <>
          {/* Current Subjects */}
          <Card>
            <CardHeader>
              <CardTitle>
                Danh sách môn của tổ hợp {selectedGroup.code}
              </CardTitle>
              <CardDescription>
                {selectedGroup.subjects && selectedGroup.subjects.length > 0
                  ? `${selectedGroup.subjects.length} môn đã được gán`
                  : "Chưa có môn nào được gán"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!selectedGroup.subjects || selectedGroup.subjects.length === 0 ? (
                <p className="text-center text-muted-foreground py-8">
                  Tổ hợp này chưa có môn học nào. Thêm môn bên dưới.
                </p>
              ) : (
                <div className="space-y-2">
                  {selectedGroup.subjects
                    .sort((a: SubjectInGroup, b: SubjectInGroup) => a.position - b.position)
                    .map((subject: SubjectInGroup) => {
                      // Find the full subject to get its id
                      const fullSubject = subjects.find((s: Subject) => s.code === subject.code);
                      return (
                        <div
                          key={subject.code}
                          className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/50 transition-colors"
                        >
                          <div className="flex items-center gap-3">
                            <Badge variant="outline" className="w-8 justify-center">
                              {subject.position}
                            </Badge>
                            <div>
                              <p className="font-medium">{subject.name_vi}</p>
                              <p className="text-sm text-muted-foreground">{subject.code}</p>
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => fullSubject && handleRemoveSubject(fullSubject.id)}
                            disabled={!fullSubject}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      );
                    })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Add Subject */}
          <Card>
            <CardHeader>
              <CardTitle>Thêm Môn học</CardTitle>
              <CardDescription>
                Chọn môn học để thêm vào tổ hợp này
              </CardDescription>
            </CardHeader>
            <CardContent>
              {availableSubjects.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">
                  Tất cả môn học đã được thêm vào tổ hợp này.
                </p>
              ) : (
                <div className="flex gap-2">
                  <Select
                    value={selectedSubjectId}
                    onValueChange={setSelectedSubjectId}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Chọn môn học..." />
                    </SelectTrigger>
                    <SelectContent>
                      {availableSubjects.map((subject: Subject) => (
                        <SelectItem key={subject.id} value={subject.id.toString()}>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm">{subject.code}</span>
                            <span>- {subject.name_vi}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    onClick={handleAddSubject}
                    disabled={!selectedSubjectId || addMutation.isPending}
                  >
                    <Plus className="h-4 w-4 mr-2" />
                    Thêm
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
