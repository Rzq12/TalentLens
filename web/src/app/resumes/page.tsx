import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { Icon } from "@/components/Icon";
import { SyntheticNotice } from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { RESUMES } from "@/lib/demo";
import { Dropzone } from "@/components/intake/Dropzone";
import { ExtractedProfile } from "@/components/intake/ExtractedProfile";

export const metadata = { title: "Resume intake — TalentLens" };

const TALLY = [
  { label: "Accessioned", value: "1,248", tone: "neutral" as const },
  { label: "In queue", value: "12", tone: "pending" as const },
  { label: "Failed to parse", value: "3", tone: "broken" as const },
];

export default function ResumesPage() {
  return (
    <>
      <Masthead
        title="Resume intake"
        meta={
          <>
            <MetaFact label="Register" value="Accessions" />
            <MetaFact label="Today" value="6 documents" mono />
          </>
        }
        seal={
          <SealBlock
            tone="pending"
            label="Queue"
            value="12 awaiting"
            meta="ETA ~3m"
          />
        }
        actions={
          <Button variant="stamp" icon="upload">
            Add documents
          </Button>
        }
      />

      <SyntheticNotice />

      {/* Accession tally — three declared facts on a ruled strip, not stat cards. */}
      <div className="grid grid-cols-1 divide-y divide-rule-hair border-b-2 border-rule-section bg-leaf sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {TALLY.map((t) => (
          <div
            key={t.label}
            className="flex items-baseline gap-3 px-5 py-3 md:px-8"
          >
            <span className="stamp-label w-28 shrink-0">{t.label}</span>
            <span
              className={`font-mono text-xl tabular-nums ${
                t.tone === "broken"
                  ? "text-seal"
                  : t.tone === "pending"
                    ? "text-ochre"
                    : "text-ink"
              }`}
            >
              {t.value}
            </span>
          </div>
        ))}
      </div>

      <Dropzone />

      <Ledger className="border-t-2 border-rule-section bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Seq
          </Th>
          <Th>Candidate &amp; document</Th>
          <Th width="10rem">Parse</Th>
          <Th width="8rem" align="center">
            OCR
          </Th>
          <Th width="10rem">Sanitisation</Th>
          <Th width="6rem" align="right">
            Pages
          </Th>
          <Th width="11rem">Accessioned</Th>
        </LedgerHead>
        <tbody>
          {RESUMES.map((r, i) => {
            const failed = r.status === "failed";
            return (
              <Tr key={r.id} className={failed ? "bg-seal-wash/40" : ""}>
                <GutterCell
                  ordinal={i + 1}
                  first={i === 0}
                  last={i === RESUMES.length - 1}
                  broken={failed}
                  live={r.status === "processing"}
                />
                <Td>
                  <div className="font-medium text-ink">
                    {failed ? (
                      <span className="text-ink-3">
                        Unresolved — name not extracted
                      </span>
                    ) : (
                      r.candidate
                    )}
                  </div>
                  <div className="truncate font-mono text-2xs text-ink-3">
                    {r.filename} · {r.id}
                  </div>
                  {r.note ? (
                    <p className="mt-1 flex items-start gap-1.5 text-xs text-seal">
                      <Icon name="alert" size={12} className="mt-[3px]" />
                      {r.note}
                    </p>
                  ) : null}
                </Td>
                <Td>
                  <Seal
                    tone={
                      r.status === "parsed"
                        ? "intact"
                        : r.status === "processing"
                          ? "pending"
                          : "broken"
                    }
                  >
                    {r.status === "parsed"
                      ? "Parsed"
                      : r.status === "processing"
                        ? "Processing"
                        : "Failed"}
                  </Seal>
                </Td>
                <Td align="center">
                  {r.ocr ? (
                    <Seal tone="pending" glyph="sheet">
                      Fallback used
                    </Seal>
                  ) : (
                    <span className="font-mono text-2xs text-ink-3">
                      Not needed
                    </span>
                  )}
                </Td>
                <Td>
                  <Seal tone={r.sanitized === "clean" ? "intact" : "neutral"}>
                    {r.sanitized === "clean" ? "Clean" : "Unverified"}
                  </Seal>
                </Td>
                <Td align="right" className="font-mono tabular-nums text-ink-2">
                  {r.pages}
                </Td>
                <Td className="font-mono text-2xs text-ink-3">{r.uploaded}</Td>
              </Tr>
            );
          })}
        </tbody>
      </Ledger>

      <ExtractedProfile />
    </>
  );
}
