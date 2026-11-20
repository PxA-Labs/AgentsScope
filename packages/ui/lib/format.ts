/** Local wall-clock time (HH:MM:SS) of an ISO 8601 timestamp, or "" if empty. */
export function formatTimestamp(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
