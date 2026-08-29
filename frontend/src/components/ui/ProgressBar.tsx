import clsx from "clsx";

export function ProgressBar({
  value,
  indeterminate,
  className,
}: {
  value: number | null;
  indeterminate?: boolean;
  className?: string;
}) {
  const pct = value === null ? 0 : Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div className={clsx("h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800", className)}>
      {indeterminate || value === null ? (
        <div className="h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-brand-500" />
      ) : (
        <div
          className="h-full rounded-full bg-brand-500 transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      )}
    </div>
  );
}
