"use client";

import { Icon, type IconName } from "@/components/Icon";

const CONTROL =
  "w-full rounded-sm border border-rule-entry bg-leaf px-2.5 py-[7px] text-sm text-ink transition-colors duration-150 ease-out hover:border-ink-3 focus:border-stamp focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-stamp disabled:cursor-not-allowed disabled:border-rule-hair disabled:bg-recess disabled:text-ink-3";

export function TextField({
  label,
  hint,
  error,
  icon,
  className = "",
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
  error?: string;
  icon?: IconName;
}) {
  return (
    <label className={`block ${className}`}>
      {label ? <span className="stamp-label mb-1 block">{label}</span> : null}
      <span className="relative block">
        {icon ? (
          <Icon
            name={icon}
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
          />
        ) : null}
        <input
          {...rest}
          aria-invalid={error ? true : undefined}
          className={`${CONTROL} ${icon ? "pl-8" : ""} ${
            error ? "border-seal focus:border-seal" : ""
          }`}
        />
      </span>
      {error ? (
        <span className="mt-1 flex items-center gap-1 text-xs text-seal">
          <Icon name="alert" size={12} />
          {error}
        </span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-ink-3">{hint}</span>
      ) : null}
    </label>
  );
}

export function SelectField({
  label,
  children,
  className = "",
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className={`block ${className}`}>
      {label ? <span className="stamp-label mb-1 block">{label}</span> : null}
      <span className="relative block">
        <select {...rest} className={`${CONTROL} appearance-none pr-8`}>
          {children}
        </select>
        <Icon
          name="chevron-down"
          size={14}
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-3"
        />
      </span>
    </label>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="inline-flex h-5 w-9 items-center rounded-sm border border-rule-entry bg-recess p-[2px] transition-colors duration-150 ease-out hover:border-ink-3 aria-checked:border-stamp aria-checked:bg-stamp-wash disabled:cursor-not-allowed disabled:opacity-55"
    >
      <span
        className={`h-3.5 w-3.5 rounded-[1px] transition-transform duration-150 ease-out ${
          checked ? "translate-x-4 bg-stamp" : "translate-x-0 bg-ink-3"
        }`}
      />
    </button>
  );
}
