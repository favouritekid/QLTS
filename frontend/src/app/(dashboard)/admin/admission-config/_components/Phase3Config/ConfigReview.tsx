"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowLeft, Send, CheckCircle2, FileText } from "lucide-react";
import { toast } from "sonner";
import { useActivateAdmissionPath, usePathDocuments } from "@/hooks/admissions/useAdmissionPaths";
import { AdmissionPathResponse, SubjectGroupNested } from "@/lib/zod/admission-path";
import { getPathStatusLabel, getPathStatusColor } from "@/lib/zod/admission-path";

interface ConfigReviewProps {
  path: AdmissionPathResponse;
  onBack: () => void;
  onFinish: () => void;
}

export function ConfigReview({ path, onBack, onFinish }: ConfigReviewProps) {
  const activateMutation = useActivateAdmissionPath();
  const isActivating = activateMutation.isPending;

  // Fetch documents
  const { data: documents = [], isLoading: loadingDocuments } = usePathDocuments(path.id);

  const handleActivate = async () => {
    try {
      await activateMutation.mutateAsync(path.id);
      toast.success("Đã kích hoạt đợt tuyển sinh thành công");
      onFinish();
    } catch (error) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err?.response?.data?.detail || "Kích hoạt thất bại");
    }
  };

  const handleFinish = () => {
    if (path.status === "draft") {
      toast.info("Đã lưu cấu hình (Trạng thái: Nháp)");
    }
    onFinish();
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex justify-between items-start">
          <div>
            <CardTitle>Bước 4: Xem lại & Hoàn tất</CardTitle>
            <CardDescription>
              Kiểm tra lại toàn bộ cấu hình trước khi kích hoạt
            </CardDescription>
          </div>
          <Badge className={getPathStatusColor(path.status)}>
            {getPathStatusLabel(path.status)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-8">
        
        {/* 1. Basic Info */}
        <section className="space-y-3">
          <h3 className="font-semibold text-lg flex items-center">
            <CheckCircle2 className="h-4 w-4 mr-2 text-green-600" />
            Thông tin chung
          </h3>
          <div className="grid grid-cols-2 gap-4 text-sm border p-4 rounded-md bg-muted/20">
            <div>
              <span className="text-muted-foreground block text-xs">Phương thức tuyển sinh</span>
              <span className="font-medium">{path.admission_method?.name} <span className="text-muted-foreground">({path.admission_method?.code})</span></span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Tên hiển thị</span>
              <span className="font-medium">{path.display_name || "--"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Thứ tự hiển thị</span>
              <span className="font-medium">{path.display_order}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Hiển thị</span>
              <span className="font-medium">{path.visibility === "public" ? "Công khai" : "Nội bộ"}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Trạng thái hiện tại</span>
              <span className="font-medium capitalize">{getPathStatusLabel(path.status)}</span>
            </div>
          </div>
        </section>

        {/* 2. Criteria */}
        <section className="space-y-3">
          <h3 className="font-semibold text-lg flex items-center">
            <CheckCircle2 className="h-4 w-4 mr-2 text-green-600" />
            Tiêu chí xét tuyển
          </h3>
          {path.criteria ? (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm border p-4 rounded-md bg-muted/20">
              <div>
                <span className="text-muted-foreground block text-xs">Min GPA</span>
                <span className="font-medium">{path.criteria.min_gpa ?? "Không áp dụng"}</span>
              </div>
              <div>
                <span className="text-muted-foreground block text-xs">Min Score (Tổng)</span>
                <span className="font-medium">{path.criteria.min_score ?? "Không áp dụng"}</span>
              </div>
              <div>
                <span className="text-muted-foreground block text-xs">Điểm liệt (Môn)</span>
                <span className="font-medium">{path.criteria.min_subject_score ?? "Không áp dụng"}</span>
              </div>
              <div>
                <span className="text-muted-foreground block text-xs">Cách tính điểm</span>
                <span className="font-medium">
                  {path.criteria.scoring_method === "sum" ? "Tổng điểm" : "Trung bình"}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground block text-xs">Chế độ chọn môn</span>
                <span className="font-medium">
                  {path.criteria.subject_selection_mode === "fixed" ? "Cố định (Theo tổ hợp)" : "Linh hoạt (Best N)"}
                </span>
              </div>
              <div className="col-span-2">
                 <span className="text-muted-foreground block text-xs">Tổ hợp môn cho phép</span>
                 <div className="flex flex-wrap gap-1 mt-1">
                   {path.criteria.subject_groups.length > 0 ? (
                     path.criteria.subject_groups.map((g: SubjectGroupNested) => (
                       <Badge key={g.id} variant="secondary">{g.code}</Badge>
                     ))
                   ) : (
                     <span className="text-muted-foreground italic">Chưa chọn tổ hợp</span>
                   )}
                 </div>
              </div>
               {path.criteria.conditions && (
                <div className="col-span-3 mt-2 border-t pt-2">
                   <span className="text-muted-foreground block text-xs">Ghi chú / Điều kiện phụ</span>
                   <p className="italic text-muted-foreground mt-1">{path.criteria.conditions}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-yellow-600 border border-yellow-200 bg-yellow-50 p-4 rounded-md">
              Chưa cấu hình tiêu chí. Vui lòng quay lại Bước 2.
            </div>
          )}
        </section>

        {/* 3. Document Requirements */}
        <section className="space-y-3">
          <h3 className="font-semibold text-lg flex items-center">
            <CheckCircle2 className="h-4 w-4 mr-2 text-green-600" />
            Hồ sơ yêu cầu
          </h3>
          {loadingDocuments ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : documents.length > 0 ? (
            <div className="border p-4 rounded-md bg-muted/20">
              <div className="space-y-3">
                {documents.map((doc, idx) => (
                  <div key={doc.document_type_id} className="flex items-start gap-3 text-sm">
                    <div className="flex-shrink-0 mt-0.5">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="flex-1">
                      <div className="font-medium">
                        {idx + 1}. {doc.document_type_name}
                        <span className="text-xs text-muted-foreground ml-2">({doc.document_type_code})</span>
                      </div>
                      <div className="flex gap-2 mt-1">
                        {doc.is_mandatory && (
                          <Badge variant="destructive" className="text-xs">Bắt buộc</Badge>
                        )}
                        {doc.requires_upload && (
                          <Badge variant="outline" className="text-xs">Cần tải lên</Badge>
                        )}
                        {doc.submission_format && (
                          <span className="text-xs text-muted-foreground">
                            Format: {doc.submission_format}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-sm text-yellow-600 border border-yellow-200 bg-yellow-50 p-4 rounded-md">
              Chưa cấu hình hồ sơ. Vui lòng quay lại Bước 3.
            </div>
          )}
        </section>

        {/* 4. Validation & Actions */}
        <section className="space-y-4 pt-4 border-t">
          {path.validation_errors.length > 0 && (
             <div className="bg-destructive/10 text-destructive text-sm p-4 rounded-md">
               <p className="font-semibold mb-1">Không thể kích hoạt do các lỗi sau:</p>
               <ul className="list-disc list-inside">
                 {path.validation_errors.map((err, idx) => (
                   <li key={idx}>{err}</li>
                 ))}
               </ul>
             </div>
          )}

          <div className="flex justify-between items-center">
            <Button variant="outline" onClick={onBack}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Quay lại
            </Button>
            
            <div className="flex gap-2">
              <Button variant="outline" onClick={handleFinish}>
                Lưu & Đóng (Không kích hoạt)
              </Button>
              
              <Button 
                onClick={handleActivate} 
                disabled={!path.can_activate || isActivating || path.status === "active"}
                className={path.status === "active" ? "bg-green-600 hover:bg-green-700" : ""}
              >
                {isActivating ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : path.status === "active" ? (
                  <CheckCircle2 className="h-4 w-4 mr-2" />
                ) : (
                  <Send className="h-4 w-4 mr-2" />
                )}
                {path.status === "active" ? "Đang hoạt động" : "Kích hoạt Tuyển sinh"}
              </Button>
            </div>
          </div>
        </section>
        
      </CardContent>
    </Card>
  );
}
