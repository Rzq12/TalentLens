import Link from "next/link";
import { Icon } from "@/components/Icon";
import { RailBar } from "@/components/shell/RegisterRail";

/**
 * The ruled masthead. Identity left, integrity seal and stamped action right,
 * separated by the heavy section rule. Present on every screen — this is the
 * consistent affordance the whole register shares.
 */
export function Masthead({
  crumbs,
  title,
  meta,
  seal,
  actions,
}: {
  crumbs?: { label: string; href?: string }[];
  title: string;
  meta?: React.ReactNode;
  seal?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="bg-leaf">
      <RailBar />
      <div className="border-b border-rule-hair px-5 pt-3 md:px-8">
        {crumbs?.length ? (
          <nav aria-label="Breadcrumb" className="mb-1.5">
            <ol className="flex flex-wrap items-center gap-1.5">
              {crumbs.map((c, i) => (
                <li key={c.label} className="flex items-center gap-1.5">
                  {i > 0 ? (
                    <Icon
                      name="chevron-right"
                      size={11}
                      className="text-ink-3"
                    />
                  ) : null}
                  {c.href ? (
                    <Link
                      href={c.href}
                      className="stamp-label text-ink-3 no-underline hover:text-stamp hover:underline"
                    >
                      {c.label}
                    </Link>
                  ) : (
                    <span className="stamp-label">{c.label}</span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        ) : null}

        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3 pb-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold track-tight text-ink">
              {title}
            </h1>
            {meta ? (
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
                {meta}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {seal}
            {actions}
          </div>
        </div>
      </div>
      <div className="rule-section" />
    </header>
  );
}

/** A labelled fact in the masthead meta row. */
export function MetaFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="stamp-label">{label}</span>
      <span
        className={
          mono ? "font-mono text-xs tabular-nums text-ink" : "text-ink"
        }
      >
        {value}
      </span>
    </span>
  );
}
