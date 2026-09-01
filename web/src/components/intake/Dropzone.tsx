"use client";

import { useCallback, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/Button";

/**
 * Accession bay. A ruled deposit frame, not a rounded dashed card — the
 * hover state deepens the rule and stamps the frame rather than tinting it.
 */
export function Dropzone({
  onUpload,
  uploading = false,
}: {
  onUpload: (files: File[], candidateName: string) => Promise<void>;
  uploading?: boolean;
}) {
  const [over, setOver] = useState(false);
  const [candidateName, setCandidateName] = useState("");
  const [queued, setQueued] = useState<File[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const accept = useCallback((files: FileList | null) => {
    if (!files?.length) return;
    setQueued((prev) => [...Array.from(files), ...prev].slice(0, 4));
  }, []);

  const submit = async () => {
    if (!queued.length || !candidateName.trim()) return;
    await onUpload(queued, candidateName.trim());
    setQueued([]);
    setCandidateName("");
  };

  return (
    <section className="border-b border-rule-entry bg-leaf px-5 py-4 md:px-8">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          accept(e.dataTransfer.files);
        }}
        className={`flex flex-wrap items-center justify-between gap-4 border-2 px-5 py-6 transition-colors duration-150 ease-out ${
          over
            ? "border-stamp bg-stamp-wash"
            : "border-dashed border-rule-entry bg-paper"
        }`}
      >
        <div className="flex items-start gap-4">
          <Icon
            name="upload"
            size={26}
            className={over ? "mt-0.5 text-stamp" : "mt-0.5 text-ink-3"}
          />
          <div>
            <h2 className="text-lg font-semibold track-tight text-ink">
              Deposit documents for accession
            </h2>
            <p className="mt-1 max-w-[64ch] text-sm text-ink-2">
              PDF, DOCX and scanned images up to 25 MB each. Scanned pages
              without a text layer fall back to OCR, and any page that fails is
              reported here rather than silently dropped.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={candidateName}
            onChange={(event) => setCandidateName(event.currentTarget.value)}
            placeholder="Candidate name"
            aria-label="Candidate name"
            className="w-44 border border-rule-entry bg-leaf px-3 py-2 text-sm text-ink"
          />
          <input
            ref={input}
            type="file"
            multiple
            className="sr-only"
            onChange={(e) => accept(e.target.files)}
            aria-label="Choose resume files to accession"
          />
          <Button
            variant="stamp"
            icon="plus"
            onClick={() => input.current?.click()}
          >
            Choose files
          </Button>
        </div>
      </div>

      {queued.length ? (
        <div className="mt-3 border border-rule-entry">
          <ul className="divide-y divide-rule-hair">
            {queued.map((file, i) => (
              <li
                key={`${file.name}-${file.lastModified}-${i}`}
                className="flex items-center gap-3 px-3 py-2"
              >
                <span className="font-mono text-2xs tabular-nums text-ink-3">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  className="developing h-2.5 w-2.5 shrink-0 bg-stamp"
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink">
                  {file.name}
                </span>
                <span className="stamp-label">Queued for accession</span>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-3 border-t border-rule-entry px-3 py-2">
            <span className="text-xs text-ink-2">
              Ready to send to accession
            </span>
            <Button
              variant="stamp"
              icon="upload"
              disabled={uploading || !candidateName.trim()}
              onClick={submit}
            >
              {uploading ? "Uploading..." : "Upload documents"}
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
