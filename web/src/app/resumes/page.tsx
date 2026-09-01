"use client";

import { useState } from "react";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { Icon } from "@/components/Icon";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { Dropzone } from "@/components/intake/Dropzone";
import { useResumes, useUploadResume } from "@/lib/hooks";

export default function ResumesPage() {
  const { data: resumesData, loading, error } = useResumes(50);
  const resumes = resumesData ?? [];
  const { upload, loading: uploading } = useUploadResume();

  const accessioned = resumes.filter((r) => r.parse_status === "ok").length;
  const failed = resumes.filter((r) => r.parse_status === "failed").length;
  const processing = resumes.filter(
    (r) => r.parse_status !== "ok" && r.parse_status !== "failed",
  ).length;

  const TALLY = [
    { label: "Accessioned", value: accessioned, tone: "neutral" as const },
    { label: "In queue", value: processing, tone: "pending" as const },
    { label: "Failed to parse", value: failed, tone: "broken" as const },
  ];

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">Error loading resumes</p>
          <p className="text-sm text-ink-3 mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Masthead
        title="Resume intake"
        meta={
          <>
            <MetaFact label="Register" value="Accessions" />
            <MetaFact
              label="Total"
              value={`${resumes.length} documents`}
              mono
            />
          </>
        }
        seal={
          <SealBlock
            tone={processing > 0 ? "pending" : "intact"}
            label="Queue"
            value={processing > 0 ? `${processing} awaiting` : "All processed"}
            meta={processing > 0 ? "Processing..." : "Up to date"}
          />
        }
        actions={
          <Button variant="stamp" icon="upload">
            Add documents
          </Button>
        }
      />

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
              {loading ? "—" : t.value}
            </span>
          </div>
        ))}
      </div>

      <Dropzone
        uploading={uploading}
        onUpload={async (files, candidateName) => {
          for (const file of files) {
            await upload(file, candidateName, undefined, false);
          }
        }}
      />

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
          {loading ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">Loading resumes...</div>
              </Td>
            </Tr>
          ) : resumes.length === 0 ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">No resumes accessioned yet</div>
              </Td>
            </Tr>
          ) : (
            resumes.map((r, i) => {
              const isFailed = r.parse_status === "failed";
              const isLowYield = r.parse_status === "low_yield";
              const parseSealTone = isFailed
                ? "broken"
                : isLowYield
                  ? "pending"
                  : "intact";
              const parseLabel = isFailed
                ? "Failed"
                : isLowYield
                  ? "Low yield"
                  : "Parsed";

              return (
                <Tr
                  key={r.document_id}
                  className={isFailed ? "bg-seal-wash/40" : ""}
                >
                  <GutterCell
                    ordinal={i + 1}
                    first={i === 0}
                    last={i === resumes.length - 1}
                    broken={isFailed}
                  />
                  <Td>
                    <div className="font-medium text-ink">
                      {isFailed ? (
                        <span className="text-ink-3">
                          Unresolved — name not extracted
                        </span>
                      ) : (
                        r.filename.replace(/\.[^/.]+$/, "")
                      )}
                    </div>
                    <div className="truncate font-mono text-2xs text-ink-3">
                      {r.filename} · {r.document_id}
                    </div>
                  </Td>
                  <Td>
                    <Seal tone={parseSealTone}>{parseLabel}</Seal>
                  </Td>
                  <Td align="center">
                    {r.needs_ocr ? (
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
                    <Seal
                      tone={
                        r.injection_risk_score != null &&
                        r.injection_risk_score < 0.3
                          ? "intact"
                          : "neutral"
                      }
                    >
                      {r.injection_risk_score != null &&
                      r.injection_risk_score < 0.3
                        ? "Clean"
                        : "Unverified"}
                    </Seal>
                  </Td>
                  <Td
                    align="right"
                    className="font-mono tabular-nums text-ink-2"
                  >
                    {r.page_count}
                  </Td>
                  <Td className="font-mono text-2xs text-ink-3">
                    {new Date(r.created_at).toLocaleString()}
                  </Td>
                </Tr>
              );
            })
          )}
        </tbody>
      </Ledger>
    </>
  );
}
