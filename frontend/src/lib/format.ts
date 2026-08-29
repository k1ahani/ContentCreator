/** Formatting helpers shared across pages. Persian-locale where it matters. */

const persianNumberFormatter = new Intl.NumberFormat("fa-IR");

export function formatNumber(value: number): string {
  return persianNumberFormatter.format(value);
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "۰ بایت";
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${persianNumberFormatter.format(Number(value.toFixed(value >= 10 ? 0 : 1)))} ${units[exponent]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.round(Math.max(0, seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.round(diffMs / 60000);

  if (diffMin < 1) return "چند لحظه پیش";
  if (diffMin < 60) return `${formatNumber(diffMin)} دقیقه پیش`;
  const diffHour = Math.round(diffMin / 60);
  if (diffHour < 24) return `${formatNumber(diffHour)} ساعت پیش`;
  const diffDay = Math.round(diffHour / 24);
  if (diffDay < 30) return `${formatNumber(diffDay)} روز پیش`;
  return new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "long", day: "numeric" }).format(date);
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("fa-IR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}
