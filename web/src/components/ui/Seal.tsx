import { Icon, type IconName } from "@/components/Icon";

/**
 * The seal block: this world's status atom. Double-ruled, never a pill,
 * never colour-only — each tone carries a distinct glyph and a distinct
 * border treatment so status survives greyscale and colour-blindness.
 */

export type SealTone = "intact" | "pending" | "broken" | "neutral" | "draft";

const TONE: Record<SealTone, { box: string; glyph: IconName; text: string }> = {
  intact: {
    box: "border-stamp text-stamp bg-stamp-wash",
    glyph: "check",
    text: "text-stamp",
  },
  pending: {
    box: "border-ochre text-ochre bg-ochre-wash",
    glyph: "clock",
    text: "text-ochre",
  },
  broken: {
    box: "border-seal text-seal bg-seal-wash",
    glyph: "alert",
    text: "text-seal",
  },
  neutral: {
    box: "border-rule-entry text-ink-2 bg-recess",
    glyph: "dash",
    text: "text-ink-2",
  },
  draft: {
    box: "border-dashed border-ink-3 text-ink-2 bg-transparent",
    glyph: "sheet",
    text: "text-ink-2",
  },
};

export function Seal({
  tone = "neutral",
  children,
  glyph,
  className = "",
}: {
  tone?: SealTone;
  children: React.ReactNode;
  glyph?: IconName | false;
  className?: string;
}) {
  const t = TONE[tone];
  const icon = glyph === false ? null : (glyph ?? t.glyph);
  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-2 py-[3px] font-narrow text-2xs font-semibold uppercase leading-3.5 track-stamp ${t.box} ${className}`}
    >
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}

/**
 * The monumental seal: the masthead integrity block. One fact, given scale,
 * because one fact here actually is the most important thing on the screen.
 */
export function SealBlock({
  tone = "intact",
  label,
  value,
  meta,
}: {
  tone?: SealTone;
  label: string;
  value: string;
  meta?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={`flex items-stretch border-y-2 ${
        tone === "broken"
          ? "border-seal"
          : tone === "pending"
            ? "border-ochre"
            : "border-rule-section"
      }`}
    >
      <div className={`flex items-center px-2.5 ${t.text}`}>
        <Icon name={t.glyph} size={18} />
      </div>
      <div className="border-l border-rule-hair py-1.5 pl-3 pr-4">
        <div className="stamp-label">{label}</div>
        <div
          className={`font-narrow text-sm font-semibold track-stamp uppercase ${t.text}`}
        >
          {value}
        </div>
      </div>
      {meta ? (
        <div className="flex items-center border-l border-rule-hair px-3 font-mono text-2xs text-ink-3">
          {meta}
        </div>
      ) : null}
    </div>
  );
}
