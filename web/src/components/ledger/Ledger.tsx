/**
 * The ledger. A ruled register, not a card-wrapped data grid: it runs
 * full-bleed to the section rules and carries the 64px sequence gutter that
 * appears on every screen in this world — the one global axis.
 */

export function Ledger({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`w-full overflow-x-auto ${className}`}>
      <table className="w-full min-w-[62rem] border-collapse text-left">
        {children}
      </table>
    </div>
  );
}

export function LedgerHead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="sticky top-0 z-10 bg-register">
      <tr className="border-b border-rule-entry">{children}</tr>
    </thead>
  );
}

export function Th({
  children,
  align = "left",
  width,
  scope = "col",
  className = "",
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  scope?: "col" | "row";
  className?: string;
}) {
  return (
    <th
      scope={scope}
      style={width ? { width } : undefined}
      className={`stamp-label px-3 py-2 align-bottom font-narrow ${
        align === "right"
          ? "text-right"
          : align === "center"
            ? "text-center"
            : "text-left"
      } ${className}`}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className = "",
  ...rest
}: React.TdHTMLAttributes<HTMLTableCellElement> & {
  align?: "left" | "right" | "center";
}) {
  return (
    <td
      {...rest}
      className={`px-3 py-2.5 align-middle text-sm ${
        align === "right"
          ? "text-right"
          : align === "center"
            ? "text-center"
            : "text-left"
      } ${className}`}
    >
      {children}
    </td>
  );
}

export function Tr({
  children,
  className = "",
  ...rest
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      {...rest}
      className={`border-b border-rule-hair transition-colors duration-150 ease-out hover:bg-recess/60 ${className}`}
    >
      {children}
    </tr>
  );
}

/**
 * The sequence gutter cell. Carries the tabular ordinal and the continuity
 * tick: a hairline spine that joins consecutive entries while the chain holds
 * and breaks into a dashed seal-red run exactly where a human overrode.
 */
export function GutterCell({
  ordinal,
  broken = false,
  live = false,
  first = false,
  last = false,
}: {
  ordinal: number | string;
  broken?: boolean;
  live?: boolean;
  first?: boolean;
  last?: boolean;
}) {
  return (
    <td className="relative w-gutter px-0 align-middle">
      {!first ? (
        <span
          aria-hidden="true"
          data-broken={broken || undefined}
          data-live={live || undefined}
          className="tick-spine top-0 h-1/2"
        />
      ) : null}
      {!last ? (
        <span
          aria-hidden="true"
          data-broken={broken || undefined}
          data-live={live || undefined}
          className="tick-spine bottom-0 h-1/2"
        />
      ) : null}
      <span
        className={`relative z-[1] mx-auto flex h-6 w-8 items-center justify-center border font-mono text-2xs tabular-nums ${
          broken
            ? "border-seal bg-seal-wash text-seal"
            : live
              ? "border-stamp bg-stamp text-leaf"
              : "border-rule-entry bg-leaf text-ink-2"
        }`}
      >
        {ordinal}
      </span>
    </td>
  );
}

/** The empty state: teaches the register rather than announcing a void. */
export function LedgerEmpty({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="border-t border-rule-hair px-8 py-14 text-center">
      <div
        aria-hidden="true"
        className="mx-auto mb-4 h-12 w-9 border border-dashed border-rule-entry bg-leaf"
      />
      <h3 className="text-lg font-semibold track-tight text-ink">{title}</h3>
      <p className="mx-auto mt-1.5 max-w-[52ch] text-sm text-ink-2">{body}</p>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}

/** Skeleton rows: the sheet develops, it never spins. */
export function LedgerSkeleton({
  rows = 5,
  cols = 6,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="border-b border-rule-hair">
          <td className="w-gutter px-0">
            <span className="developing mx-auto block h-6 w-8 bg-recess" />
          </td>
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c} className="px-3 py-2.5">
              <span
                className="developing block h-3 bg-recess"
                style={{ width: `${45 + ((r * 7 + c * 13) % 45)}%` }}
              />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}
