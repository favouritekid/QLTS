"use client"

/**
 * Tuition Tab Component
 * 
 * Displays tuition fee information and payment history.
 * Note: Full payment integration requires backend API.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { CreditCard, Receipt, AlertCircle, CheckCircle, Clock } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface TuitionTabProps {
  profile: AdmissionProfileResponse
}

// Mock tuition data (will be replaced with API data)
const MOCK_TUITION = {
  total_amount: 45000000, // 45 triệu
  discount_amount: 5000000, // 5 triệu (scholarship)
  paid_amount: 20000000, // 20 triệu đã đóng
  payments: [
    {
      id: 1,
      amount: 10000000,
      method: "bank_transfer",
      date: "2024-01-15",
      status: "completed",
      receipt_no: "RCP-2024-001",
    },
    {
      id: 2,
      amount: 10000000,
      method: "cash",
      date: "2024-02-20",
      status: "completed",
      receipt_no: "RCP-2024-002",
    },
  ],
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
  }).format(amount)
}

export function TuitionTab({ profile }: TuitionTabProps) {
  // TODO: Replace with real API call when backend is ready
  const tuition = MOCK_TUITION
  const finalAmount = tuition.total_amount - tuition.discount_amount
  const remainingAmount = finalAmount - tuition.paid_amount
  const isPaid = remainingAmount <= 0
  const isEnrolled = profile.status === "enrolled"

  return (
    <div className="space-y-6">
      {/* Tuition Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Thông tin học phí
          </CardTitle>
          <CardDescription>
            Học phí và các khoản thanh toán
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="p-4 bg-muted/50 rounded-lg">
              <p className="text-sm text-muted-foreground">Tổng học phí</p>
              <p className="text-xl font-bold">{formatCurrency(tuition.total_amount)}</p>
            </div>
            
            <div className="p-4 bg-green-50 rounded-lg">
              <p className="text-sm text-green-600">Học bổng/Giảm</p>
              <p className="text-xl font-bold text-green-700">
                - {formatCurrency(tuition.discount_amount)}
              </p>
            </div>
            
            <div className="p-4 bg-blue-50 rounded-lg">
              <p className="text-sm text-blue-600">Đã thanh toán</p>
              <p className="text-xl font-bold text-blue-700">
                {formatCurrency(tuition.paid_amount)}
              </p>
            </div>
            
            <div className={`p-4 rounded-lg ${isPaid ? "bg-green-50" : "bg-orange-50"}`}>
              <p className={`text-sm ${isPaid ? "text-green-600" : "text-orange-600"}`}>
                Còn lại
              </p>
              <p className={`text-xl font-bold ${isPaid ? "text-green-700" : "text-orange-700"}`}>
                {formatCurrency(remainingAmount)}
              </p>
            </div>
          </div>
          
          <Separator className="my-6" />
          
          {/* Payment Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isPaid ? (
                <>
                  <CheckCircle className="h-5 w-5 text-green-500" />
                  <span className="font-medium text-green-700">Đã thanh toán đủ</span>
                </>
              ) : (
                <>
                  <Clock className="h-5 w-5 text-orange-500" />
                  <span className="font-medium text-orange-700">Chưa thanh toán đủ</span>
                </>
              )}
            </div>
            
            {!isPaid && isEnrolled && (
              <Button>
                <CreditCard className="h-4 w-4 mr-2" />
                Thanh toán
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Payment History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Receipt className="h-5 w-5" />
            Lịch sử thanh toán
          </CardTitle>
          <CardDescription>
            {tuition.payments.length} giao dịch
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tuition.payments.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Receipt className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p>Chưa có giao dịch nào</p>
            </div>
          ) : (
            <div className="space-y-3">
              {tuition.payments.map((payment) => (
                <div
                  key={payment.id}
                  className="flex items-center justify-between p-3 border rounded-lg"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-green-100 rounded">
                      <CheckCircle className="h-4 w-4 text-green-600" />
                    </div>
                    <div>
                      <p className="font-medium">{formatCurrency(payment.amount)}</p>
                      <p className="text-xs text-muted-foreground">
                        {payment.receipt_no} • {new Date(payment.date).toLocaleDateString("vi-VN")}
                      </p>
                    </div>
                  </div>
                  
                  <Badge variant="outline">
                    {payment.method === "bank_transfer" ? "Chuyển khoản" : "Tiền mặt"}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Backend API Notice */}
      <Card className="border-dashed border-amber-300 bg-amber-50/50">
        <CardContent className="pt-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-amber-700">Lưu ý phát triển</p>
              <p className="text-amber-600">
                Dữ liệu học phí hiện là mock data. Cần implement backend API:
              </p>
              <ul className="list-disc pl-4 mt-1 text-amber-600">
                <li>GET /api/admissions/{"{id}"}/tuition</li>
                <li>POST /api/admissions/{"{id}"}/payments</li>
                <li>GET /api/admissions/{"{id}"}/payments</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
