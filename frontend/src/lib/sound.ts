// src/lib/sound.ts
/**
 * Sound notification utility
 */

let audioContext: AudioContext | null = null;

/**
 * Initialize audio context (required for some browsers)
 */
function getAudioContext(): AudioContext {
  if (!audioContext) {
    const WebkitAudioContext = (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    audioContext = new (window.AudioContext || WebkitAudioContext!)();
  }
  return audioContext;
}

/**
 * Play a notification sound using Web Audio API
 * Creates a pleasant notification tone programmatically
 */
export function playNotificationSound(): void {
  try {
    const context = getAudioContext();

    // Chrome autoplay policy: context tạo lazy ngoài user-gesture (vd khi bật
    // âm được KHÔI PHỤC từ localStorage lúc tải trang) sẽ ở trạng thái
    // "suspended" → âm phát ra câm. Resume để chuông thật sự kêu.
    if (context.state === "suspended") {
      void context.resume();
    }

    // Create oscillator for the notification sound
    const oscillator = context.createOscillator();
    const gainNode = context.createGain();

    // Connect nodes
    oscillator.connect(gainNode);
    gainNode.connect(context.destination);

    // Configure sound (pleasant notification tone)
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(800, context.currentTime); // 800 Hz
    oscillator.frequency.setValueAtTime(600, context.currentTime + 0.1); // 600 Hz

    // Fade in and out
    gainNode.gain.setValueAtTime(0, context.currentTime);
    gainNode.gain.linearRampToValueAtTime(0.3, context.currentTime + 0.05);
    gainNode.gain.linearRampToValueAtTime(0, context.currentTime + 0.2);

    // Play the sound
    oscillator.start(context.currentTime);
    oscillator.stop(context.currentTime + 0.2);
  } catch (error) {
    console.error("Failed to play notification sound:", error);
  }
}

/**
 * Play notification sound from an audio file
 * @param audioPath Path to the audio file (e.g., "/sounds/notification.mp3")
 */
export function playNotificationSoundFromFile(audioPath: string): void {
  try {
    const audio = new Audio(audioPath);
    audio.volume = 0.5; // 50% volume
    audio.play().catch((error) => {
      console.error("Failed to play notification sound:", error);
    });
  } catch (error) {
    console.error("Failed to play notification sound:", error);
  }
}

/**
 * Request notification permission if not already granted
 */
export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!("Notification" in window)) {
    console.warn("This browser does not support notifications");
    return "denied";
  }

  if (Notification.permission === "granted") {
    return "granted";
  }

  if (Notification.permission !== "denied") {
    const permission = await Notification.requestPermission();
    return permission;
  }

  return Notification.permission;
}

/**
 * Show browser notification
 */
export function showBrowserNotification(
  title: string,
  options?: NotificationOptions
): void {
  if (!("Notification" in window)) {
    console.warn("This browser does not support notifications");
    return;
  }

  if (Notification.permission === "granted") {
    new Notification(title, options);
  } else if (Notification.permission !== "denied") {
    Notification.requestPermission().then((permission) => {
      if (permission === "granted") {
        new Notification(title, options);
      }
    });
  }
}
