// src/app/(dashboard)/settings/notifications/_components/NotificationSettingsClient.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import {
  Bell,
  Bot,
  Copy,
  Mail,
  MessageCircle,
  Monitor,
  Save,
  Smartphone,
  Volume2,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  notificationPreferenceKeys,
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  useEventGroupPreferences,
  useUpdateEventGroupPreference,
  type EventGroupPreferencesResponse,
} from "@/hooks/useNotificationPreferences";
import {
  useGenerateLinkCode,
  useUnlinkZaloBot,
  useZaloBotLinkStatus,
} from "@/hooks/useZaloBotLink";
import type {
  NotificationPreference,
  NotificationPreferenceUpdate,
  ZaloBotLinkCode,
} from "@/types/api.types";

interface NotificationSettingsClientProps {
  initialPreferences?: NotificationPreference;
  initialEventGroups?: EventGroupPreferencesResponse;
}

export function NotificationSettingsClient({
  initialPreferences,
  initialEventGroups,
}: NotificationSettingsClientProps) {
  // General preferences
  const { data: preferences } = useNotificationPreferences({
    initialData: initialPreferences,
  });
  const updatePreferences = useUpdateNotificationPreferences();

  // Event group preferences (NEW)
  const { data: eventGroupData } = useEventGroupPreferences({
    initialData: initialEventGroups,
  });
  const updateEventGroupPreference = useUpdateEventGroupPreference();

  // Track if initial data has been loaded to prevent re-initialization
  const initializedRef = useRef(false);

  // Local form state - initialize from server data when available
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [browserEnabled, setBrowserEnabled] = useState(true);
  const [emailDigest, setEmailDigest] = useState("instant");
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(false);
  const [quietHoursStart, setQuietHoursStart] = useState("22:00");
  const [quietHoursEnd, setQuietHoursEnd] = useState("08:00");

  // Sync local state with server data only once when data first loads
  useEffect(() => {
    if (preferences && !initializedRef.current) {
      initializedRef.current = true;
      // Defer setState to avoid synchronous updates in effect
      queueMicrotask(() => {
        setEmailEnabled(preferences.email_enabled ?? true);
        setSoundEnabled(preferences.sound_enabled ?? true);
        setBrowserEnabled(preferences.browser_enabled ?? true);
        setEmailDigest(preferences.email_digest ?? "instant");
        setQuietHoursEnabled(preferences.quiet_hours_enabled ?? false);
        setQuietHoursStart(preferences.quiet_hours_start ?? "22:00");
        setQuietHoursEnd(preferences.quiet_hours_end ?? "08:00");
      });
    }
  }, [preferences]);

  const handleSaveGeneralSettings = async () => {
    const updateData: NotificationPreferenceUpdate = {
      email_enabled: emailEnabled,
      sound_enabled: soundEnabled,
      browser_enabled: browserEnabled,
      email_digest: emailDigest as "instant" | "daily" | "weekly" | "disabled",
      quiet_hours_enabled: quietHoursEnabled,
      quiet_hours_start: quietHoursEnabled ? quietHoursStart : null,
      quiet_hours_end: quietHoursEnabled ? quietHoursEnd : null,
    };

    try {
      await updatePreferences.mutateAsync(updateData);
      toast.success("Cập nhật cài đặt thành công!");
    } catch {
      toast.error("Lỗi khi cập nhật cài đặt");
    }
  };

  const handleToggleGroupPreference = async (
    group: string,
    channel: string,
    enabled: boolean
  ) => {
    try {
      await updateEventGroupPreference.mutateAsync({
        event_group: group,
        channel,
        enabled,
      });
      // No toast for individual toggles - they update instantly
    } catch {
      toast.error("Lỗi khi cập nhật tuỳ chọn thông báo");
    }
  };

  // ─────────────────────────────────────────────────────────────────
  // v5 Step 22: Zalo Bot link section
  // ─────────────────────────────────────────────────────────────────
  const queryClient = useQueryClient();
  const [pendingCode, setPendingCode] = useState<ZaloBotLinkCode | null>(null);
  const { data: linkStatus } = useZaloBotLinkStatus({
    pollWhileWaiting: !!pendingCode,
  });
  const generateLinkCode = useGenerateLinkCode();
  const unlinkZaloBot = useUnlinkZaloBot();

  // v5 Step 22 / Phase 6a fix: when the link flips active server-side
  // (via the bot webhook, NOT through this component), only the
  // ``linkStatus`` poll observes it. The ``zalo_bot_enabled`` column
  // ships back via ``useNotificationPreferences``, whose cache stays
  // stale until something invalidates it — leaving the per-group
  // zalo_bot toggle disabled until a hard refresh.
  // Invalidate the preferences scope here so the toggle becomes
  // interactive within one render.
  useEffect(() => {
    if (linkStatus?.is_linked && pendingCode) {
      setPendingCode(null);
      queryClient.invalidateQueries({ queryKey: notificationPreferenceKeys.all });
      toast.success("Đã liên kết Zalo Bot thành công!");
    }
  }, [linkStatus?.is_linked, pendingCode, queryClient]);

  const handleGenerateLinkCode = async () => {
    try {
      const code = await generateLinkCode.mutateAsync();
      setPendingCode(code);
    } catch {
      toast.error("Không tạo được mã liên kết. Vui lòng thử lại.");
    }
  };

  const handleUnlinkZaloBot = async () => {
    try {
      const res = await unlinkZaloBot.mutateAsync();
      setPendingCode(null);
      if (res.unlinked) toast.success(res.message || "Đã huỷ liên kết.");
      else toast.info(res.message || "Tài khoản chưa được liên kết.");
    } catch {
      toast.error("Không huỷ được liên kết. Vui lòng thử lại.");
    }
  };

  const handleCopyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      toast.success("Đã sao chép mã.");
    } catch {
      // Clipboard may be denied (insecure context, browser policy).
      toast.info(`Mã: ${code}`);
    }
  };

  const isLinked = !!linkStatus?.is_linked;
  const zaloBotEnabled = preferences?.zalo_bot_enabled ?? false;

  return (
    <div className="space-y-6">
      {/* General Settings */}
      <Card className="max-w-4xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Cài đặt chung
              </CardTitle>
              <CardDescription>Chọn cách bạn muốn nhận thông báo</CardDescription>
            </div>
            <Button
              onClick={handleSaveGeneralSettings}
              disabled={updatePreferences.isPending}
              size="sm"
            >
              <Save className="mr-2 h-4 w-4" />
              Lưu
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Email Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="email-enabled" className="text-base flex items-center gap-2">
                <Mail className="h-4 w-4" />
                Thông báo qua Email
              </Label>
              <p className="text-sm text-muted-foreground">
                Nhận thông báo qua email
              </p>
            </div>
            <Switch
              id="email-enabled"
              checked={emailEnabled}
              onCheckedChange={setEmailEnabled}
            />
          </div>

          {/* Email Digest */}
          {emailEnabled && (
            <div className="flex items-center justify-between pl-4 border-l-2">
              <div className="space-y-0.5">
                <Label htmlFor="email-digest" className="text-base">
                  Tần suất tổng hợp Email
                </Label>
                <p className="text-sm text-muted-foreground">
                  Tần suất gửi thông báo email
                </p>
              </div>
              <Select
                value={emailDigest}
                onValueChange={(value) => setEmailDigest(value as "instant" | "daily" | "weekly" | "disabled")}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="instant">Ngay lập tức</SelectItem>
                  <SelectItem value="daily">Tổng hợp hàng ngày</SelectItem>
                  <SelectItem value="weekly">Tổng hợp hàng tuần</SelectItem>
                  <SelectItem value="disabled">Tắt</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <Separator />

          {/* Browser Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="browser-enabled" className="text-base flex items-center gap-2">
                <Monitor className="h-4 w-4" />
                Thông báo trình duyệt
              </Label>
              <p className="text-sm text-muted-foreground">
                Hiện thông báo trong ứng dụng
              </p>
            </div>
            <Switch
              id="browser-enabled"
              checked={browserEnabled}
              onCheckedChange={setBrowserEnabled}
            />
          </div>

          <Separator />

          {/* Sound Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="sound-enabled" className="text-base flex items-center gap-2">
                <Volume2 className="h-4 w-4" />
                Thông báo âm thanh
              </Label>
              <p className="text-sm text-muted-foreground">
                Phát âm thanh khi có thông báo
              </p>
            </div>
            <Switch
              id="sound-enabled"
              checked={soundEnabled}
              onCheckedChange={setSoundEnabled}
            />
          </div>
        </CardContent>
      </Card>

      {/* Quiet Hours */}
      <Card className="max-w-4xl">
        <CardHeader>
          <CardTitle>Giờ yên tĩnh (Không làm phiền)</CardTitle>
          <CardDescription>
            Tắt tiếng thông báo trong khoảng thời gian nhất định
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="quiet-hours-enabled" className="text-base">
                Bật giờ yên tĩnh
              </Label>
              <p className="text-sm text-muted-foreground">
                Thông báo sẽ bị tắt tiếng trong khoảng thời gian này
              </p>
            </div>
            <Switch
              id="quiet-hours-enabled"
              checked={quietHoursEnabled}
              onCheckedChange={setQuietHoursEnabled}
            />
          </div>

          {quietHoursEnabled && (
            <div className="grid gap-4 md:grid-cols-2 pl-4 border-l-2">
              <div className="space-y-2">
                <Label htmlFor="quiet-hours-start">Giờ bắt đầu</Label>
                <input
                  id="quiet-hours-start"
                  type="time"
                  value={quietHoursStart}
                  onChange={(e) => setQuietHoursStart(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="quiet-hours-end">Giờ kết thúc</Label>
                <input
                  id="quiet-hours-end"
                  type="time"
                  value={quietHoursEnd}
                  onChange={(e) => setQuietHoursEnd(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Zalo Bot Link (v5 Step 22) */}
      <Card className="max-w-4xl" data-testid="zalo-bot-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            Liên kết Zalo Bot
          </CardTitle>
          <CardDescription>
            Nhận thông báo nội bộ qua Zalo Bot. Liên kết một lần — bot sẽ chủ
            động gửi tin về tài khoản Zalo của bạn.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLinked ? (
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <Badge variant="default">Đã liên kết</Badge>
                  {linkStatus?.display_name && (
                    <span className="text-sm font-medium">
                      {linkStatus.display_name}
                    </span>
                  )}
                </div>
                {linkStatus?.linked_at && (
                  <p className="text-xs text-muted-foreground">
                    Liên kết từ:{" "}
                    {new Date(linkStatus.linked_at).toLocaleString("vi-VN")}
                  </p>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleUnlinkZaloBot}
                disabled={unlinkZaloBot.isPending}
                data-testid="zalo-bot-unlink"
              >
                Huỷ liên kết
              </Button>
            </div>
          ) : pendingCode ? (
            <div className="space-y-3 rounded-lg border-2 border-dashed p-4">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">Mã liên kết</Label>
                <Badge variant="secondary">
                  Hết hạn sau{" "}
                  {Math.round(pendingCode.expires_in_seconds / 60)} phút
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <code
                  className="flex-1 rounded bg-muted px-4 py-3 text-2xl font-mono tracking-widest"
                  data-testid="zalo-bot-code"
                >
                  {pendingCode.code}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleCopyCode(pendingCode.code)}
                  aria-label="Sao chép mã"
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                {pendingCode.instructions}
              </p>
              <p className="text-xs text-muted-foreground">
                Hệ thống sẽ tự động cập nhật khi bạn gửi mã vào Zalo Bot.
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <p className="text-sm font-medium">Chưa liên kết</p>
                <p className="text-xs text-muted-foreground">
                  Bấm tạo mã để bắt đầu liên kết tài khoản Zalo.
                </p>
              </div>
              <Button
                size="sm"
                onClick={handleGenerateLinkCode}
                disabled={generateLinkCode.isPending}
                data-testid="zalo-bot-generate"
              >
                <MessageCircle className="mr-2 h-4 w-4" />
                Tạo mã liên kết
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Event Group Preferences (NEW) */}
      <Card className="max-w-4xl">
        <CardHeader>
          <CardTitle>Danh mục thông báo</CardTitle>
          <CardDescription>
            Tuỳ chỉnh thông báo cho từng danh mục. Thay đổi được lưu tự động.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Header — v5 Step 22: 5 columns now (added Zalo Bot) */}
          <div className="grid grid-cols-5 gap-4 px-4 text-sm font-medium text-muted-foreground">
            <div>Danh mục</div>
            <div className="text-center flex items-center justify-center gap-1">
              <Monitor className="h-4 w-4" />
              Trình duyệt
            </div>
            <div className="text-center flex items-center justify-center gap-1">
              <Mail className="h-4 w-4" />
              Email
            </div>
            <div className="text-center flex items-center justify-center gap-1">
              <Bot className="h-4 w-4" />
              Zalo Bot
            </div>
            <div className="text-center flex items-center justify-center gap-1">
              <Smartphone className="h-4 w-4" />
              SMS (Sắp có)
            </div>
          </div>

          <Separator />

          {/* Event Groups */}
          {eventGroupData?.groups.map((group) => {
            const prefs = eventGroupData.preferences[group.id] || {
              browser: true,
              email: true,
              zalo_bot: false,
              sms: false,
            };

            return (
              <div
                key={group.id}
                className="grid grid-cols-5 gap-4 items-center px-4 py-3 rounded-lg hover:bg-muted/50 transition-colors"
              >
                <div>
                  <div className="font-medium flex items-center gap-2">
                    {group.name_vi || group.name_en}
                    {group.id === "system" && (
                      <Badge variant="secondary" className="text-xs">
                        Quan trọng
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {group.description_vi || group.description_en}
                  </p>
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.browser ?? true}
                    onCheckedChange={(enabled) =>
                      handleToggleGroupPreference(group.id, "browser", enabled)
                    }
                    disabled={!browserEnabled || updateEventGroupPreference.isPending}
                  />
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.email ?? true}
                    onCheckedChange={(enabled) =>
                      handleToggleGroupPreference(group.id, "email", enabled)
                    }
                    disabled={!emailEnabled || updateEventGroupPreference.isPending}
                  />
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.zalo_bot ?? false}
                    onCheckedChange={(enabled) =>
                      handleToggleGroupPreference(group.id, "zalo_bot", enabled)
                    }
                    // v5 Step 22: per-group toggle is dead unless the
                    // user has both linked the bot AND backend reports
                    // ``zalo_bot_enabled=true`` — same column the Gate A
                    // filter checks. Tooltip surfaces the reason.
                    disabled={
                      !zaloBotEnabled
                      || updateEventGroupPreference.isPending
                    }
                    data-testid={`zalo-bot-toggle-${group.id}`}
                    aria-label={
                      zaloBotEnabled
                        ? `Zalo Bot — ${group.name_vi || group.name_en}`
                        : "Zalo Bot — chưa liên kết"
                    }
                  />
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.sms ?? false}
                    onCheckedChange={(enabled) =>
                      handleToggleGroupPreference(group.id, "sms", enabled)
                    }
                    disabled={true} // SMS not yet implemented
                  />
                </div>
              </div>
            );
          })}

          {/* Legend */}
          <div className="pt-4 border-t">
            <p className="text-xs text-muted-foreground">
              * Thông báo trình duyệt hiển thị ở biểu tượng chuông. Email được
              gửi đến email đã đăng ký. Zalo Bot chỉ khả dụng sau khi liên kết
              ở mục phía trên. Tính năng SMS sắp ra mắt.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
