"use client";

import { useCallback, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/Button";

/**
 * Accession bay. A ruled deposit frame, not a rounded dashed card — the
 * hover state deepens the rule and stamps the frame rather than tinting it.
 */
export function Dropzone() {
  const [over, setOver] = useState(false);
  const [queued, setQueued] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const accept = useCallback((files: FileList | null) => {
    if (!files?.length) return;
    setQueued((prev) =>
      [...Array.from(files).map((f) => f.name), ...prev].slice(0, 4),
    );
  }, []);

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
        <ul className="mt-3 divide-y divide-rule-hair border border-rule-entry">
          {queued.map((name, i) => (
            <li
              key={`${name}-${i}`}
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
                {name}
              </span>
              <span className="stamp-label">Queued for accession</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
