import React, { useState } from 'react';
import { Phone, PhoneCall, Mail, MapPin, Calendar, Clock, ChevronDown, ChevronRight, MessageSquare, Video, Users, MoreHorizontal, Edit, Trash2, FileText, CheckCircle2, Circle, AlertCircle, Star, TrendingUp, Target, Zap, User, GraduationCap, Building, Globe, ChevronUp, X, Check, Bell } from 'lucide-react';

export default function LeadDetailsWireframe() {
  const [activeTab, setActiveTab] = useState('overview');
  const [scoringExpanded, setScoringExpanded] = useState(false);
  const [selectedMethod, setSelectedMethod] = useState('call');
  const [selectedResult, setSelectedResult] = useState(null);
  const [callbackTime, setCallbackTime] = useState(null);
  const [noteText, setNoteText] = useState('');

  const consultMethods = [
    { id: 'call', icon: PhoneCall, label: 'Gọi điện' },
    { id: 'email', icon: Mail, label: 'Email' },
    { id: 'video', icon: Video, label: 'Video' },
    { id: 'sms', icon: MessageSquare, label: 'SMS' },
    { id: 'meet', icon: Users, label: 'Gặp mặt' },
  ];

  const callResults = [
    { id: 'no_answer', label: 'Không liên lạc được', color: 'bg-gray-100 text-gray-700 border-gray-200' },
    { id: 'interested', label: 'Quan tâm, cần tư vấn thêm', color: 'bg-blue-50 text-blue-700 border-blue-200' },
    { id: 'callback', label: 'Hẹn gọi lại', color: 'bg-amber-50 text-amber-700 border-amber-200' },
    { id: 'ready', label: 'Sẵn sàng nộp hồ sơ', color: 'bg-green-50 text-green-700 border-green-200' },
    { id: 'rejected', label: 'Từ chối / Không phù hợp', color: 'bg-red-50 text-red-700 border-red-200' },
  ];

  const callbackOptions = [
    { id: '30m', label: '30 phút' },
    { id: '1h', label: '1 giờ' },
    { id: '3h', label: '3 giờ' },
    { id: 'tomorrow', label: 'Ngày mai' },
    { id: 'custom', label: 'Tuỳ chọn' },
  ];

  const admissionChecklist = [
    { id: 1, label: 'Đã xác nhận ngành học', checked: true },
    { id: 2, label: 'Đã hiểu về học phí & chính sách', checked: true },
    { id: 3, label: 'Đã cung cấp giấy tờ cần thiết', checked: false },
    { id: 4, label: 'Đã đồng ý nộp hồ sơ', checked: false },
  ];

  const consultHistory = [
    {
      id: 1,
      type: 'call',
      status: 'Đã kết nối liên hệ',
      officer: 'Phạm Thái Hà',
      time: '21:06',
      date: 'Hôm nay',
      note: 'Đã kết nối liên hệ, KH quan tâm ngành Điều dưỡng',
      result: 'interested'
    },
    {
      id: 2,
      type: 'call',
      status: 'Có nhu cầu tìm hiểu',
      officer: 'Phạm Thái Hà',
      time: '14:42',
      date: 'Hôm qua',
      note: 'Đã gọi điện tư vấn và đang có nhu cầu, hẹn gọi lại',
      result: 'callback'
    },
    {
      id: 3,
      type: 'system',
      status: 'Phân công lead',
      officer: 'Võ Thị Thu Thu Hiền',
      time: '14:09',
      date: '20/01',
      note: 'Hệ thống phân công tự động',
      result: 'system'
    },
  ];

  return (
    <div className="min-h-screen bg-slate-50" style={{ fontFamily: "'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      {/* Top Navigation */}
      <nav className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <GraduationCap className="w-5 h-5 text-white" />
          </div>
          <div className="flex items-center text-sm text-slate-500">
            <span className="hover:text-slate-700 cursor-pointer">Dashboard</span>
            <ChevronRight className="w-4 h-4 mx-2" />
            <span className="hover:text-slate-700 cursor-pointer">Lead List</span>
            <ChevronRight className="w-4 h-4 mx-2" />
            <span className="text-slate-900 font-medium">Lead Details</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
            Tìm kiếm...
          </button>
        </div>
      </nav>

      {/* Workflow Tabs */}
      <div className="bg-white border-b border-slate-200 px-6">
        <div className="flex items-center gap-1">
          {['Tư vấn', 'Xét tuyển', 'Học phí', 'Nhập học'].map((tab, index) => (
            <button
              key={tab}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                index === 0 
                  ? 'border-indigo-600 text-indigo-600 bg-indigo-50/50' 
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* ===== HEADER: ACTION ZONE ===== */}
      <div className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="flex items-start justify-between">
          {/* Left: Lead Info */}
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center text-white text-xl font-bold shadow-lg shadow-indigo-200">
              PT
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-slate-900">Phạm Thái</h1>
                <span className="text-sm text-slate-400">#532</span>
                <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 text-xs font-medium rounded-full border border-emerald-200">
                  Đã kết nối
                </span>
              </div>
              <div className="flex items-center gap-4 mt-1.5 text-sm text-slate-600">
                <span className="flex items-center gap-1.5">
                  <GraduationCap className="w-4 h-4 text-slate-400" />
                  Điều dưỡng
                </span>
                <span className="flex items-center gap-1.5">
                  <Target className="w-4 h-4 text-amber-500" />
                  <span className="font-semibold text-amber-600">80 điểm</span>
                  <span className="text-slate-400">• Tiềm năng cao</span>
                </span>
              </div>
            </div>
          </div>

          {/* Center: PHONE - Primary Action */}
          <div className="flex items-center gap-3 bg-slate-50 rounded-2xl p-3 border border-slate-200">
            <div className="flex flex-col items-end">
              <a href="tel:0906513555" className="text-lg font-bold text-slate-900 hover:text-indigo-600 transition-colors">
                0906 513 555
              </a>
              <span className="text-xs text-slate-400">SĐT chính</span>
            </div>
            <button className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-semibold rounded-xl hover:from-emerald-600 hover:to-emerald-700 transition-all shadow-lg shadow-emerald-200 hover:shadow-emerald-300 hover:scale-105 active:scale-95">
              <PhoneCall className="w-5 h-5" />
              GỌI NGAY
            </button>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 transition-colors shadow-lg shadow-indigo-200">
              <FileText className="w-4 h-4" />
              Tạo hồ sơ tuyển sinh
            </button>
            <button className="p-2.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-xl transition-colors">
              <MoreHorizontal className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* ===== ACTION BANNER ===== */}
      <div className="mx-6 mt-4">
        <div className="flex items-center justify-between p-4 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-2xl">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-amber-100 rounded-xl flex items-center justify-center">
              <Bell className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-amber-800">ACTION CẦN LÀM</span>
                <span className="px-2 py-0.5 bg-amber-200 text-amber-800 text-xs font-medium rounded-full">Ưu tiên</span>
              </div>
              <p className="text-sm text-amber-700 mt-0.5">
                <Clock className="w-3.5 h-3.5 inline mr-1" />
                Hẹn gọi lại lúc <strong>15:00 hôm nay</strong> — KH muốn hỏi thêm về học phí
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100 rounded-lg transition-colors">
              Đánh dấu hoàn thành
            </button>
            <button className="px-4 py-2 text-sm font-medium bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors">
              Gọi ngay
            </button>
          </div>
        </div>
      </div>

      {/* ===== MAIN CONTENT ===== */}
      <div className="px-6 py-4 grid grid-cols-12 gap-4">
        
        {/* ===== LEFT PANEL: Reference Info ===== */}
        <div className="col-span-4 space-y-4">
          
          {/* Tabs */}
          <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
            <div className="flex border-b border-slate-200">
              {[
                { id: 'overview', label: 'Tổng quan' },
                { id: 'history', label: 'Lịch sử' },
                { id: 'profile', label: 'Hồ sơ' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex-1 px-4 py-3 text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? 'text-indigo-600 bg-indigo-50 border-b-2 border-indigo-600'
                      : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab Content */}
            <div className="p-4">
              {activeTab === 'overview' && (
                <div className="space-y-4">
                  {/* Contact */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Liên hệ</h3>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl">
                        <div className="flex items-center gap-3">
                          <Phone className="w-4 h-4 text-slate-400" />
                          <span className="text-sm font-medium text-slate-700">0906 513 555</span>
                        </div>
                        <span className="text-xs text-emerald-600 font-medium">Chính</span>
                      </div>
                      <div className="flex items-center justify-between p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                        <div className="flex items-center gap-3">
                          <Phone className="w-4 h-4 text-slate-400" />
                          <span className="text-sm text-slate-600">0775 191 411</span>
                        </div>
                        <span className="text-xs text-slate-400">Phụ</span>
                      </div>
                      <div className="flex items-center gap-3 p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                        <Mail className="w-4 h-4 text-slate-400" />
                        <span className="text-sm text-slate-600">hapham1388@gmail.com</span>
                      </div>
                      <div className="flex items-center gap-3 p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                        <MapPin className="w-4 h-4 text-slate-400" />
                        <span className="text-sm text-slate-600">Buôn Ma Thuột</span>
                      </div>
                    </div>
                  </div>

                  {/* Personal Info */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Thông tin cá nhân</h3>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="p-2.5 bg-slate-50 rounded-xl">
                        <div className="text-xs text-slate-400">Năm sinh</div>
                        <div className="text-sm font-medium text-slate-700">1988</div>
                      </div>
                      <div className="p-2.5 bg-slate-50 rounded-xl">
                        <div className="text-xs text-slate-400">Vị trí địa lý</div>
                        <div className="text-sm font-medium text-slate-700">Xa</div>
                      </div>
                      <div className="p-2.5 bg-slate-50 rounded-xl col-span-2">
                        <div className="text-xs text-slate-400">Liên quan nghề</div>
                        <div className="text-sm font-medium text-slate-700">Gián tiếp</div>
                      </div>
                    </div>
                  </div>

                  {/* Education - Warning for weak student */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Học vấn</h3>
                    <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl">
                      <div className="flex items-center gap-2 mb-2">
                        <AlertCircle className="w-4 h-4 text-amber-500" />
                        <span className="text-xs font-semibold text-amber-700">Lưu ý khi tư vấn</span>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <div className="text-xs text-amber-600">Trình độ</div>
                          <div className="text-sm font-semibold text-amber-800">THPT</div>
                        </div>
                        <div>
                          <div className="text-xs text-amber-600">Học lực</div>
                          <div className="text-sm font-semibold text-amber-800">Yếu</div>
                        </div>
                        <div>
                          <div className="text-xs text-amber-600">GPA</div>
                          <div className="text-sm font-semibold text-amber-800">5.0</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Source */}
                  <div>
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Nguồn & Phân công</h3>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-500">Nguồn</span>
                        <span className="text-sm font-medium text-slate-700 flex items-center gap-1.5">
                          <Globe className="w-3.5 h-3.5" />
                          Website
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-500">Tư vấn viên</span>
                        <span className="text-sm font-medium text-slate-700">Võ Thị Thu Hiền</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'history' && (
                <div className="space-y-3">
                  {consultHistory.map((item, index) => (
                    <div 
                      key={item.id}
                      className={`p-3 rounded-xl border transition-colors ${
                        index === 0 ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {item.type === 'call' ? (
                            <div className="w-7 h-7 bg-emerald-100 rounded-lg flex items-center justify-center">
                              <PhoneCall className="w-3.5 h-3.5 text-emerald-600" />
                            </div>
                          ) : (
                            <div className="w-7 h-7 bg-slate-100 rounded-lg flex items-center justify-center">
                              <Zap className="w-3.5 h-3.5 text-slate-500" />
                            </div>
                          )}
                          <div>
                            <div className="text-sm font-medium text-slate-800">{item.status}</div>
                            <div className="text-xs text-slate-400">{item.officer}</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-medium text-slate-600">{item.time}</div>
                          <div className="text-xs text-slate-400">{item.date}</div>
                        </div>
                      </div>
                      <p className="text-sm text-slate-600 pl-9">{item.note}</p>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'profile' && (
                <div className="text-center py-8">
                  <div className="w-12 h-12 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-3">
                    <FileText className="w-6 h-6 text-slate-400" />
                  </div>
                  <p className="text-sm text-slate-500">Chưa có hồ sơ tuyển sinh</p>
                  <button className="mt-3 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors">
                    + Tạo hồ sơ mới
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Scoring - Collapsed by default */}
          <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
            <button 
              onClick={() => setScoringExpanded(!scoringExpanded)}
              className="w-full flex items-center justify-between p-4 hover:bg-slate-50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-indigo-100 rounded-lg flex items-center justify-center">
                  <TrendingUp className="w-4 h-4 text-indigo-600" />
                </div>
                <div className="text-left">
                  <div className="text-sm font-semibold text-slate-800">Lead Scoring</div>
                  <div className="text-xs text-slate-400">Điểm tổng hợp: 65/100</div>
                </div>
              </div>
              {scoringExpanded ? (
                <ChevronUp className="w-5 h-5 text-slate-400" />
              ) : (
                <ChevronDown className="w-5 h-5 text-slate-400" />
              )}
            </button>
            
            {scoringExpanded && (
              <div className="px-4 pb-4 border-t border-slate-100">
                <div className="grid grid-cols-2 gap-3 mt-4">
                  <div className="p-3 bg-slate-50 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Điểm tổng hợp</div>
                    <div className="text-2xl font-bold text-indigo-600">65<span className="text-sm font-normal text-slate-400">/100</span></div>
                    <div className="w-full bg-slate-200 rounded-full h-1.5 mt-2">
                      <div className="bg-indigo-500 h-1.5 rounded-full" style={{width: '65%'}}></div>
                    </div>
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Mức độ tương tác</div>
                    <div className="text-2xl font-bold text-amber-600">20<span className="text-sm font-normal text-slate-400">/100</span></div>
                    <div className="w-full bg-slate-200 rounded-full h-1.5 mt-2">
                      <div className="bg-amber-500 h-1.5 rounded-full" style={{width: '20%'}}></div>
                    </div>
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Phù hợp</div>
                    <div className="text-2xl font-bold text-emerald-600">100<span className="text-sm font-normal text-slate-400">/100</span></div>
                    <div className="w-full bg-slate-200 rounded-full h-1.5 mt-2">
                      <div className="bg-emerald-500 h-1.5 rounded-full" style={{width: '100%'}}></div>
                    </div>
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Khẩn cấp</div>
                    <div className="text-2xl font-bold text-red-500">45<span className="text-sm font-normal text-slate-400">/100</span></div>
                    <div className="w-full bg-slate-200 rounded-full h-1.5 mt-2">
                      <div className="bg-red-500 h-1.5 rounded-full" style={{width: '45%'}}></div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Admission Checklist */}
          <div className="bg-white rounded-2xl border border-slate-200 p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-800">Sẵn sàng nộp hồ sơ</h3>
              <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-1 rounded-full">
                2/4 hoàn thành
              </span>
            </div>
            <div className="space-y-2">
              {admissionChecklist.map((item) => (
                <div 
                  key={item.id}
                  className={`flex items-center gap-3 p-2.5 rounded-xl transition-colors ${
                    item.checked ? 'bg-emerald-50' : 'bg-slate-50'
                  }`}
                >
                  {item.checked ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0" />
                  ) : (
                    <Circle className="w-5 h-5 text-slate-300 flex-shrink-0" />
                  )}
                  <span className={`text-sm ${item.checked ? 'text-emerald-700' : 'text-slate-600'}`}>
                    {item.label}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-4 p-3 bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-100">
              <p className="text-xs text-indigo-700">
                <strong>Gợi ý:</strong> Cuộc gọi tiếp theo nên tập trung vào việc thu thập giấy tờ và xác nhận ý định nộp hồ sơ.
              </p>
            </div>
          </div>
        </div>

        {/* ===== RIGHT PANEL: Quick Actions ===== */}
        <div className="col-span-8 space-y-4">
          
          {/* Quick Note Form */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                <Zap className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-900">Ghi nhận tư vấn</h2>
                <p className="text-xs text-slate-400">Ghi lại kết quả cuộc gọi / liên hệ</p>
              </div>
            </div>

            {/* Method Selection */}
            <div className="mb-5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 block">
                Phương thức liên hệ
              </label>
              <div className="flex gap-2">
                {consultMethods.map((method) => (
                  <button
                    key={method.id}
                    onClick={() => setSelectedMethod(method.id)}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
                      selectedMethod === method.id
                        ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    <method.icon className="w-4 h-4" />
                    {method.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Note Input */}
            <div className="mb-5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 block">
                Nội dung ghi chú <span className="text-slate-400 font-normal">(tuỳ chọn)</span>
              </label>
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                placeholder="VD: KH hẹn gọi lại lúc 3h chiều, muốn hỏi thêm về học phí..."
                className="w-full p-4 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none transition-all"
                rows={3}
              />
            </div>

            {/* Call Result */}
            <div className="mb-5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 block">
                Kết quả cuộc gọi
              </label>
              <div className="flex flex-wrap gap-2">
                {callResults.map((result) => (
                  <button
                    key={result.id}
                    onClick={() => setSelectedResult(result.id)}
                    className={`px-4 py-2 rounded-xl text-sm font-medium border-2 transition-all ${
                      selectedResult === result.id
                        ? `${result.color} ring-2 ring-offset-2 ring-indigo-300`
                        : `${result.color} opacity-60 hover:opacity-100`
                    }`}
                  >
                    {result.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Callback Time */}
            {(selectedResult === 'callback' || selectedResult === 'interested') && (
              <div className="mb-5 p-4 bg-amber-50 rounded-xl border border-amber-200">
                <label className="text-xs font-semibold text-amber-700 uppercase tracking-wider mb-3 block">
                  <Clock className="w-3.5 h-3.5 inline mr-1" />
                  Hẹn gọi lại
                </label>
                <div className="flex flex-wrap gap-2">
                  {callbackOptions.map((option) => (
                    <button
                      key={option.id}
                      onClick={() => setCallbackTime(option.id)}
                      className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                        callbackTime === option.id
                          ? 'bg-amber-500 text-white shadow-lg'
                          : 'bg-white text-amber-700 border border-amber-300 hover:bg-amber-100'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Submit */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-100">
              <p className="text-xs text-slate-400">
                Phím tắt: <kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-600">Ctrl</kbd> + <kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-600">Enter</kbd> để lưu
              </p>
              <div className="flex items-center gap-3">
                <button className="px-5 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors">
                  Huỷ
                </button>
                <button className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-700 text-white font-semibold rounded-xl hover:from-indigo-700 hover:to-indigo-800 transition-all shadow-lg shadow-indigo-200 hover:shadow-indigo-300">
                  <Check className="w-4 h-4" />
                  Lưu ghi nhận
                </button>
              </div>
            </div>
          </div>

          {/* Recent Consultation History - Compact View */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-800">Lịch sử tư vấn gần đây</h3>
              <button className="text-xs text-indigo-600 font-medium hover:underline">
                Xem tất cả →
              </button>
            </div>
            <div className="space-y-3">
              {consultHistory.slice(0, 2).map((item) => (
                <div 
                  key={item.id}
                  className="flex items-center gap-4 p-3 bg-slate-50 rounded-xl"
                >
                  {item.type === 'call' ? (
                    <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center flex-shrink-0">
                      <PhoneCall className="w-5 h-5 text-emerald-600" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 bg-slate-200 rounded-xl flex items-center justify-center flex-shrink-0">
                      <Zap className="w-5 h-5 text-slate-500" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-800">{item.status}</span>
                      <span className="text-xs text-slate-400">{item.date} • {item.time}</span>
                    </div>
                    <p className="text-sm text-slate-500 truncate">{item.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Stats Summary */}
          <div className="grid grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-slate-200 p-4 text-center">
              <div className="text-2xl font-bold text-indigo-600">3</div>
              <div className="text-xs text-slate-500">Lần liên hệ</div>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-4 text-center">
              <div className="text-2xl font-bold text-emerald-600">2</div>
              <div className="text-xs text-slate-500">Kết nối thành công</div>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-4 text-center">
              <div className="text-2xl font-bold text-amber-600">5</div>
              <div className="text-xs text-slate-500">Ngày từ lúc tạo</div>
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-4 text-center">
              <div className="text-2xl font-bold text-purple-600">1</div>
              <div className="text-xs text-slate-500">Hẹn chưa xử lý</div>
            </div>
          </div>

        </div>
      </div>

      {/* Footer hint */}
      <div className="px-6 pb-6">
        <div className="p-4 bg-slate-100 rounded-2xl text-center">
          <p className="text-xs text-slate-500">
            💡 <strong>Wireframe này tập trung vào:</strong> Header = Action zone (SĐT + Gọi ngay) | Banner = Next action rõ ràng | Left = Thông tin tham khảo (collapsible) | Right = Form ghi nhận nhanh
          </p>
        </div>
      </div>
    </div>
  );
}
