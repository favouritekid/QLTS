// src/app/(dashboard)/settings/notifications/page.tsx
"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Bell, Save, Volume2, Mail, Monitor } from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  useEventGroupPreferences,
  useUpdateEventGroupPreference,
} from "@/hooks/useNotificationPreferences";
import type { NotificationPreferenceUpdate } from "@/types/api.types";

export default function NotificationSettingsPage() {
  // General preferences
  const { data: preferences, isLoading: isLoadingPreferences } = useNotificationPreferences();
  const updatePreferences = useUpdateNotificationPreferences();

  // Event group preferences (NEW)
  const { data: eventGroupData, isLoading: isLoadingEventGroups } = useEventGroupPreferences();
  const updateEventGroupPreference = useUpdateEventGroupPreference();

  // Track if initial data has been loaded to prevent re-initialization
  const initializedRef = useRef(false);

  // General settings state - use useMemo for initial values from server
  const initialValues = useMemo(() => ({
    emailEnabled: preferences?.email_enabled ?? true,
    soundEnabled: preferences?.sound_enabled ?? true,
    browserEnabled: preferences?.browser_enabled ?? true,
    emailDigest: preferences?.email_digest ?? "instant",
    quietHoursEnabled: preferences?.quiet_hours_enabled ?? false,
    quietHoursStart: preferences?.quiet_hours_start ?? "22:00",
    quietHoursEnd: preferences?.quiet_hours_end ?? "08:00",
  }), [preferences]);

  // Local form state
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
      setEmailEnabled(initialValues.emailEnabled);
      setSoundEnabled(initialValues.soundEnabled);
      setBrowserEnabled(initialValues.browserEnabled);
      setEmailDigest(initialValues.emailDigest);
      setQuietHoursEnabled(initialValues.quietHoursEnabled);
      setQuietHoursStart(initialValues.quietHoursStart);
      setQuietHoursEnd(initialValues.quietHoursEnd);
    }
  }, [preferences, initialValues]);

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
      toast.success("General settings updated successfully!");
    } catch {
      toast.error("Failed to update general settings");
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
      toast.error(`Failed to update ${group} ${channel} preference`);
    }
  };

  const isLoading = isLoadingPreferences || isLoadingEventGroups;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Card className="max-w-4xl">
          <CardContent className="p-6 space-y-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center justify-between">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-6 w-12" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* General Settings */}
      <Card className="max-w-4xl">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                General Settings
              </CardTitle>
              <CardDescription>Choose how you want to receive notifications</CardDescription>
            </div>
            <Button
              onClick={handleSaveGeneralSettings}
              disabled={updatePreferences.isPending}
              size="sm"
            >
              <Save className="mr-2 h-4 w-4" />
              Save
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Email Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="email-enabled" className="text-base flex items-center gap-2">
                <Mail className="h-4 w-4" />
                Email Notifications
              </Label>
              <p className="text-sm text-muted-foreground">
                Receive notifications via email
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
                  Email Digest Frequency
                </Label>
                <p className="text-sm text-muted-foreground">
                  How often to send email notifications
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
                  <SelectItem value="instant">Instant</SelectItem>
                  <SelectItem value="daily">Daily Digest</SelectItem>
                  <SelectItem value="weekly">Weekly Digest</SelectItem>
                  <SelectItem value="disabled">Disabled</SelectItem>
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
                Browser Notifications
              </Label>
              <p className="text-sm text-muted-foreground">
                Show in-app notifications
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
                Sound Notifications
              </Label>
              <p className="text-sm text-muted-foreground">
                Play sound when notifications arrive
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
          <CardTitle>Quiet Hours (Do Not Disturb)</CardTitle>
          <CardDescription>
            Mute notifications during specific hours
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="quiet-hours-enabled" className="text-base">
                Enable Quiet Hours
              </Label>
              <p className="text-sm text-muted-foreground">
                Notifications will be silent during these hours
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
                <Label htmlFor="quiet-hours-start">Start Time</Label>
                <input
                  id="quiet-hours-start"
                  type="time"
                  value={quietHoursStart}
                  onChange={(e) => setQuietHoursStart(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="quiet-hours-end">End Time</Label>
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

      {/* Event Group Preferences (NEW) */}
      <Card className="max-w-4xl">
        <CardHeader>
          <CardTitle>Notification Categories</CardTitle>
          <CardDescription>
            Customize notifications for each category. Changes are saved automatically.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Header */}
          <div className="grid grid-cols-4 gap-4 px-4 text-sm font-medium text-muted-foreground">
            <div>Category</div>
            <div className="text-center flex items-center justify-center gap-1">
              <Monitor className="h-4 w-4" />
              Browser
            </div>
            <div className="text-center flex items-center justify-center gap-1">
              <Mail className="h-4 w-4" />
              Email
            </div>
            <div className="text-center flex items-center justify-center gap-1">
              <Volume2 className="h-4 w-4" />
              Sound
            </div>
          </div>

          <Separator />

          {/* Event Groups */}
          {eventGroupData?.groups.map((group) => {
            const prefs = eventGroupData.preferences[group.id] || {
              browser: true,
              email: true,
              sms: false,
            };

            return (
              <div
                key={group.id}
                className="grid grid-cols-4 gap-4 items-center px-4 py-3 rounded-lg hover:bg-muted/50 transition-colors"
              >
                <div>
                  <div className="font-medium flex items-center gap-2">
                    {group.name_en}
                    {group.id === "system" && (
                      <Badge variant="secondary" className="text-xs">
                        Important
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {group.description_en}
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
              * Browser notifications appear in the notification bell. Email notifications are sent to your registered email.
              SMS notifications are coming soon.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
