/** A ruled form section. Declares its edge once — border or shadow, never both. */
export function FormSection({
  title,
  aside,
  children,
  className = "",
  bleed = false,
}: {
  title?: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bleed?: boolean;
}) {
  return (
    <section className={`bg-leaf ${className}`}>
      {title ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
          <h2 className="stamp-label">{title}</h2>
          {aside}
        </div>
      ) : null}
      <div className={bleed ? "" : "px-5 py-4 md:px-8"}>{children}</div>
    </section>
  );
}

/** Toolbar strip above a ledger: filters and search, ruled not carded. */
export function Toolbar({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-rule-entry bg-leaf px-5 py-3 md:px-8">
      {children}
    </div>
  );
}

/** The one statement this product must never let a surface contradict. */
export function NeverRejectsNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs text-ink-2 ${className}`}>
      TalentLens ranks and explains. It never rejects, advances or filters out a
      candidate on its own — every decision below is recorded against a named
      person.
    </p>
  );
}
