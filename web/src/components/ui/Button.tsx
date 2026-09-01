"use client";

import { Icon, type IconName } from "@/components/Icon";

/**
 * Stamped control. Square-edged form-office button with a full state set:
 * default, hover, focus, active, disabled, loading.
 */

type Variant = "stamp" | "ruled" | "quiet" | "alarm";

const VARIANT: Record<Variant, string> = {
  stamp:
    "bg-stamp text-leaf border border-stamp hover:bg-[#3d2570] active:bg-[#33205e] disabled:bg-recess disabled:text-ink-3 disabled:border-rule-entry",
  ruled:
    "bg-leaf text-ink border border-rule-section hover:bg-recess active:bg-rule-hair disabled:text-ink-3 disabled:border-rule-entry disabled:bg-transparent",
  quiet:
    "bg-transparent text-ink-2 border border-transparent hover:bg-recess hover:text-ink active:bg-rule-hair disabled:text-ink-3",
  alarm:
    "bg-transparent text-seal border border-seal hover:bg-seal-wash active:bg-[#e9cbc7] disabled:text-ink-3 disabled:border-rule-entry",
};

export function Button({
  variant = "ruled",
  icon,
  iconAfter,
  loading = false,
  children,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  icon?: IconName;
  iconAfter?: IconName;
  loading?: boolean;
}) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-sm px-3 py-[7px] font-narrow text-xs font-semibold uppercase track-stamp transition-colors duration-150 ease-out disabled:cursor-not-allowed ${VARIANT[variant]} ${className}`}
    >
      {loading ? (
        <span
          aria-hidden="true"
          className="developing inline-block h-3 w-3 border border-current"
        />
      ) : icon ? (
        <Icon name={icon} size={14} />
      ) : null}
      {children}
      {iconAfter ? <Icon name={iconAfter} size={14} /> : null}
    </button>
  );
}

export function IconButton({
  label,
  icon,
  tone = "quiet",
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  icon: IconName;
  tone?: Variant;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...rest}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-sm transition-colors duration-150 ease-out disabled:cursor-not-allowed ${VARIANT[tone]} ${className}`}
    >
      <Icon name={icon} size={15} />
    </button>
  );
}
