"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/Icon";
import { Mark } from "@/components/shell/Mark";

const ENTRIES: {
  href: string;
  label: string;
  icon: IconName;
  index: string;
}[] = [
  { href: "/jobs", label: "Jobs", icon: "register", index: "01" },
  { href: "/resumes", label: "Resumes", icon: "sheet", index: "02" },
  { href: "/runs", label: "Screening runs", icon: "run", index: "03" },
  { href: "/candidates", label: "Candidates", icon: "person", index: "04" },
  { href: "/governance", label: "Governance", icon: "seal", index: "05" },
  { href: "/settings", label: "Settings", icon: "gear", index: "06" },
];

export function RegisterRail() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Register sections"
      className="sticky top-0 z-30 hidden h-screen w-rail-narrow shrink-0 flex-col bg-register lg:flex xl:w-rail"
    >
      <div className="flex h-14 items-center gap-2.5 border-b-2 border-rule-section px-3 xl:px-4">
        <Mark />
        <span className="hidden font-narrow text-sm font-bold uppercase track-stamp text-ink xl:inline">
          TalentLens
        </span>
      </div>

      <ul className="flex-1 pt-1">
        {ENTRIES.map((e) => {
          const active =
            pathname === e.href || pathname.startsWith(`${e.href}/`);
          return (
            <li key={e.href}>
              <Link
                href={e.href}
                aria-current={active ? "page" : undefined}
                title={e.label}
                className={`group flex items-center gap-3 border-b border-rule-hair px-3 py-2.5 text-sm transition-colors duration-150 ease-out xl:px-4 ${
                  active
                    ? "bg-leaf font-semibold text-ink"
                    : "text-ink-2 hover:bg-recess hover:text-ink"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`hidden w-5 font-mono text-2xs tabular-nums xl:inline ${
                    active ? "text-stamp" : "text-ink-3"
                  }`}
                >
                  {e.index}
                </span>
                <Icon
                  name={e.icon}
                  size={17}
                  className={
                    active ? "text-stamp" : "text-ink-3 group-hover:text-ink-2"
                  }
                />
                <span className="hidden truncate xl:inline">{e.label}</span>
                {active ? (
                  <span
                    aria-hidden="true"
                    className="ml-auto hidden h-4 w-[3px] bg-stamp xl:block"
                  />
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="border-t-2 border-rule-section px-3 py-3 xl:px-4">
        <div className="hidden xl:block">
          <div className="stamp-label">Custodian</div>
          <div className="mt-0.5 truncate text-sm font-medium text-ink">
            A. Wijaya
          </div>
          <div className="truncate font-mono text-2xs text-ink-3">
            recruiter · demo tenant
          </div>
        </div>
        <div
          aria-hidden="true"
          className="flex h-8 w-8 items-center justify-center border border-rule-entry bg-leaf font-mono text-xs text-ink-2 xl:hidden"
        >
          AW
        </div>
      </div>
    </nav>
  );
}

/** Mobile / tablet section switcher — the rail collapses structurally. */
export function RailBar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Register sections"
      className="flex gap-0 overflow-x-auto border-b border-rule-entry bg-register lg:hidden"
    >
      {ENTRIES.map((e) => {
        const active = pathname === e.href || pathname.startsWith(`${e.href}/`);
        return (
          <Link
            key={e.href}
            href={e.href}
            aria-current={active ? "page" : undefined}
            className={`flex shrink-0 items-center gap-1.5 border-r border-rule-hair px-3 py-2 font-narrow text-2xs font-semibold uppercase track-stamp transition-colors duration-150 ease-out ${
              active
                ? "bg-leaf text-stamp shadow-[inset_0_-2px_0_var(--color-stamp)]"
                : "text-ink-2 hover:bg-recess"
            }`}
          >
            <Icon name={e.icon} size={14} />
            {e.label}
          </Link>
        );
      })}
    </nav>
  );
}
