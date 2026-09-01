/**
 * TalentLens mark: a custody seal reduced to geometry. Two ruled leaves
 * bound by a continuity tick — the same tick that runs every ledger gutter.
 */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className="shrink-0"
    >
      <rect
        x="2.5"
        y="2.5"
        width="19"
        height="19"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M12 2.5v19" stroke="var(--color-stamp)" strokeWidth="2" />
      <path
        d="M5.5 8h3.5M5.5 12h3.5M5.5 16h3.5"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <path
        d="M15 11.2l1.7 1.8 3.1-3.4"
        stroke="var(--color-stamp)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
