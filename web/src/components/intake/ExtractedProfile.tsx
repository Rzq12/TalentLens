import { Icon } from "@/components/Icon";
import { Seal } from "@/components/ui/Seal";
import { Button } from "@/components/ui/Button";

const FIELDS: {
  label: string;
  value: string;
  confidence: number;
  page: number;
}[] = [
  { label: "Full name", value: "Jane Doe", confidence: 99, page: 1 },
  {
    label: "Contact email",
    value: "j.doe@example.invalid",
    confidence: 98,
    page: 1,
  },
  { label: "Years of experience", value: "6.5", confidence: 94, page: 1 },
  {
    label: "Most recent title",
    value: "Senior Frontend Engineer",
    confidence: 97,
    page: 2,
  },
  {
    label: "Most recent employer",
    value: "Northwind Systems",
    confidence: 97,
    page: 2,
  },
  {
    label: "Highest qualification",
    value: "BSc Computer Science",
    confidence: 91,
    page: 4,
  },
];

/**
 * The accession sheet: what was pulled out of the document, where it came from,
 * and how sure the extractor was. Two ruled columns, no card, no JSON blob —
 * a recruiter reads fields, not braces.
 */
export function ExtractedProfile() {
  return (
    <section className="grid grid-cols-1 border-t-2 border-rule-section bg-leaf xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="border-b border-rule-entry xl:border-b-0 xl:border-r">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
          <h2 className="stamp-label">Document · RSM-88213 · page 1 of 4</h2>
          <div className="flex items-center gap-1">
            <Button variant="quiet" icon="zoom-out">
              Out
            </Button>
            <span className="px-1 font-mono text-2xs tabular-nums text-ink-2">
              125%
            </span>
            <Button variant="quiet" icon="zoom-in">
              In
            </Button>
            <Button variant="ruled" icon="download">
              Original
            </Button>
          </div>
        </div>
        <div className="flex justify-center bg-recess px-5 py-6 md:px-8">
          <div className="w-full max-w-[34rem] border border-rule-entry bg-leaf px-8 py-9 shadow-[0_1px_0_var(--color-rule-hair)]">
            <p className="text-xl font-semibold track-tight text-ink">
              Jane Doe
            </p>
            <p className="mt-0.5 font-mono text-2xs text-ink-3">
              j.doe@example.invalid · Jakarta, ID
            </p>
            <div className="mt-5 space-y-2">
              {Array.from({ length: 12 }).map((_, i) => (
                <span
                  key={i}
                  className="block h-2 bg-recess"
                  style={{ width: `${55 + ((i * 17) % 42)}%` }}
                  aria-hidden="true"
                />
              ))}
            </div>
            <p className="sr-only">
              Rendered preview of a synthetic resume document, first page.
            </p>
          </div>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-6">
          <h2 className="stamp-label">Accession sheet</h2>
          <Seal tone="intact">Extracted</Seal>
        </div>
        <dl className="divide-y divide-rule-hair">
          {FIELDS.map((f) => (
            <div key={f.label} className="px-5 py-2.5 md:px-6">
              <dt className="stamp-label">{f.label}</dt>
              <dd className="mt-0.5 flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate text-sm text-ink">
                  {f.value}
                </span>
                <span className="flex shrink-0 items-center gap-1.5 font-mono text-2xs tabular-nums text-ink-3">
                  p.{f.page}
                  <span
                    className={`inline-block h-2 w-8 border ${
                      f.confidence >= 95 ? "border-stamp" : "border-ochre"
                    }`}
                    aria-hidden="true"
                  >
                    <span
                      className={`block h-full ${
                        f.confidence >= 95 ? "bg-stamp" : "bg-ochre"
                      }`}
                      style={{ width: `${f.confidence}%` }}
                    />
                  </span>
                  {f.confidence}%
                </span>
              </dd>
            </div>
          ))}
        </dl>
        <p className="flex items-start gap-1.5 border-t border-rule-entry px-5 py-3 text-xs text-ink-2 md:px-6">
          <Icon
            name="thread"
            size={13}
            className="mt-0.5 shrink-0 text-ink-3"
          />
          Every field records the page and character offset it was read from, so
          a score built on it can always be traced back to the document.
        </p>
      </div>
    </section>
  );
}
