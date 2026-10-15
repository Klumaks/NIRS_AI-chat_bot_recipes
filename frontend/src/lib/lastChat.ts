import { useSyncExternalStore } from "react";

// Navigation preference only: never store messages or recipe data here.
const eventName = "ai-chef:last-chat";
const key = (userId: string) => "ai-chef:last-chat:" + userId;
const memory = new Map<string, string>();

function read(userId: string): string {
  let value = memory.get(userId) || "";
  try { value = localStorage.getItem(key(userId)) || ""; } catch { /* Storage can be unavailable. */ }
  return /^\/chat\/[^/]+(?:\/recipe\/\d+)?$/.test(value) ? value : "";
}
function subscribe(listener: () => void) {
  window.addEventListener(eventName, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(eventName, listener);
    window.removeEventListener("storage", listener);
  };
}
export function rememberChat(userId: string, path: string) {
  if (read(userId) === path) return;
  memory.set(userId, path);
  try { localStorage.setItem(key(userId), path); } catch { /* Retain this session's preference. */ }
  window.dispatchEvent(new Event(eventName));
}
export function forgetChat(userId: string, chatId: string) {
  const path = read(userId);
  if (path.split("/")[2] !== encodeURIComponent(chatId)) return;
  memory.delete(userId);
  try { localStorage.removeItem(key(userId)); } catch { /* No persistent preference to remove. */ }
  window.dispatchEvent(new Event(eventName));
}
export function useLastChat(userId: string) {
  return useSyncExternalStore(subscribe, () => read(userId), () => "");
}
