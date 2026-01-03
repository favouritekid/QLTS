"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { CheckCircle2, Lock, Send } from "lucide-react"

interface FinalizeTabProps {
  isEligible: boolean
  onSubmit: () => void
  isSubmitting: boolean
}

export function FinalizeTab({ isEligible, onSubmit, isSubmitting }: FinalizeTabProps) {
  return (
    <div className="max-w-2xl mx-auto space-y-6">
        <Card className="text-center py-10">
            <CardHeader>
                {isEligible ? (
                    <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
                        <CheckCircle2 className="w-8 h-8 text-green-600" />
                    </div>
                ) : (
                    <div className="mx-auto w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
                        <Lock className="w-8 h-8 text-gray-400" />
                    </div>
                )}
                
                <CardTitle className="text-2xl">
                    {isEligible ? "Hồ sơ đủ điều kiện nộp" : "Chưa đủ điều kiện"}
                </CardTitle>
                <CardDescription>
                    {isEligible 
                        ? "Tất cả các bước đánh giá đã hoàn tất. Bạn có thể nộp hồ sơ chính thức ngay bây giờ."
                        : "Vui lòng hoàn thành các bước trước và đảm bảo hồ sơ hợp lệ trước khi nộp."}
                </CardDescription>
            </CardHeader>
            <CardContent>
                <Button 
                    size="lg" 
                    className="w-full sm:w-auto min-w-[200px]" 
                    disabled={!isEligible || isSubmitting}
                    onClick={onSubmit}
                >
                    {isSubmitting ? "Đang xử lý..." : (
                        <>
                            <Send className="w-4 h-4 mr-2" />
                            Nộp hồ sơ chính thức
                        </>
                    )}
                </Button>
            </CardContent>
        </Card>
    </div>
  )
}
