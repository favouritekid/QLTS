// src/app/(dashboard)/settings/notifications/page.tsx
"use client";

import { useState } from "react";
import { Bell, Save, Volume2 } from "lucide-react";
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
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
} from "@/hooks/useNotificationPreferences";
import type { NotificationPreferenceUpdate } from "@/types/api.types";

export default function NotificationSettingsPage() {
  const { data: preferences, isLoading } = useNotificationPreferences();
  const updatePreferences = useUpdateNotificationPreferences();

  const [emailEnabled, setEmailEnabled] = useState(preferences?.email_enabled ?? true);
  const [soundEnabled, setSoundEnabled] = useState(preferences?.sound_enabled ?? true);
  const [browserEnabled, setBrowserEnabled] = useState(preferences?.browser_enabled ?? true);
  const [emailDigest, setEmailDigest] = useState(preferences?.email_digest ?? "instant");
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(
    preferences?.quiet_hours_enabled ?? false
  );
  const [quietHoursStart, setQuietHoursStart] = useState(
    preferences?.quiet_hours_start ?? "22:00"
  );
  const [quietHoursEnd, setQuietHoursEnd] = useState(preferences?.quiet_hours_end ?? "08:00");

  // Notification type preferences
  const [typePreferences, setTypePreferences] = useState(
    preferences?.type_preferences ?? {}
  );

  // Update local state when preferences load
  useState(() => {
    if (preferences) {
      setEmailEnabled(preferences.email_enabled);
      setSoundEnabled(preferences.sound_enabled);
      setBrowserEnabled(preferences.browser_enabled);
      setEmailDigest(preferences.email_digest);
      setQuietHoursEnabled(preferences.quiet_hours_enabled);
      setQuietHoursStart(preferences.quiet_hours_start ?? "22:00");
      setQuietHoursEnd(preferences.quiet_hours_end ?? "08:00");
      setTypePreferences(preferences.type_preferences ?? {});
    }
  });

  const handleSave = async () => {
    const updateData: NotificationPreferenceUpdate = {
      email_enabled: emailEnabled,
      sound_enabled: soundEnabled,
      browser_enabled: browserEnabled,
      email_digest: emailDigest as "instant" | "daily" | "weekly" | "disabled",
      quiet_hours_enabled: quietHoursEnabled,
      quiet_hours_start: quietHoursEnabled ? quietHoursStart : null,
      quiet_hours_end: quietHoursEnabled ? quietHoursEnd : null,
      type_preferences: typePreferences,
    };

    try {
      await updatePreferences.mutateAsync(updateData);
      toast.success("Notification preferences updated successfully!");
    } catch {
      toast.error("Failed to update notification preferences");
    }
  };

  const toggleTypePreference = (type: string, channel: "email" | "browser" | "sound") => {
    setTypePreferences((prev) => {
      const currentPref = prev[type] || { email: true, browser: true, sound: true };
      return {
        ...prev,
        [type]: {
          ...currentPref,
          [channel]: !currentPref[channel],
        },
      };
    });
  };

  const notificationTypes = [
    { value: "info", label: "Information" },
    { value: "success", label: "Success" },
    { value: "warning", label: "Warning" },
    { value: "error", label: "Error" },
    { value: "admin_update", label: "Admin Updates" },
    { value: "system", label: "System" },
  ];

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
      {/* Save Button */}
      <div className="flex justify-end max-w-4xl">
        <Button onClick={handleSave} disabled={updatePreferences.isPending}>
          <Save className="mr-2 h-4 w-4" />
          Save Changes
        </Button>
      </div>

      {/* General Settings */}
      <Card className="max-w-4xl">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            General Settings
          </CardTitle>
          <CardDescription>Choose how you want to receive notifications</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Email Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="email-enabled" className="text-base">
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

          <Separator />

          {/* Browser Notifications */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="browser-enabled" className="text-base">
                Browser Notifications
              </Label>
              <p className="text-sm text-muted-foreground">
                Show browser push notifications
              </p>
            </div>
            <Switch
              id="browser-enabled"
              checked={browserEnabled}
              onCheckedChange={setBrowserEnabled}
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

      {/* Per-Type Preferences */}
      <Card className="max-w-4xl">
        <CardHeader>
          <CardTitle>Notification Type Preferences</CardTitle>
          <CardDescription>
            Customize notification channels for each type
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-1 text-sm font-medium mb-4">
            <div className="grid grid-cols-4 gap-4 px-4">
              <div>Type</div>
              <div className="text-center">Email</div>
              <div className="text-center">Browser</div>
              <div className="text-center">Sound</div>
            </div>
          </div>
          {notificationTypes.map((type) => {
            const prefs = typePreferences[type.value] || {
              email: true,
              browser: true,
              sound: true,
            };

            return (
              <div key={type.value} className="grid grid-cols-4 gap-4 items-center px-4 py-2 rounded-lg hover:bg-muted/50">
                <div className="font-medium">{type.label}</div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.email ?? true}
                    onCheckedChange={() => toggleTypePreference(type.value, "email")}
                    disabled={!emailEnabled}
                  />
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.browser ?? true}
                    onCheckedChange={() => toggleTypePreference(type.value, "browser")}
                    disabled={!browserEnabled}
                  />
                </div>
                <div className="flex justify-center">
                  <Switch
                    checked={prefs.sound ?? true}
                    onCheckedChange={() => toggleTypePreference(type.value, "sound")}
                    disabled={!soundEnabled}
                  />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
