"use client";

import { useState } from "react";
import { Toggle, SelectField, TextField } from "@/components/ui/Field";
import { Icon } from "@/components/Icon";

function Row({
  title,
  body,
  control,
}: {
  title: string;
  body: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4 md:px-8">
      <div className="min-w-0 max-w-[68ch]">
        <h3 className="text-sm font-medium text-ink">{title}</h3>
        <p className="mt-0.5 text-sm text-ink-2">{body}</p>
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

export function SettingsForm() {
  const [blind, setBlind] = useState(true);
  const [autoOcr, setAutoOcr] = useState(true);
  const [requireReason, setRequireReason] = useState(true);

  return (
    <>
      <section className="bg-leaf">
        <div className="border-b border-rule-entry px-5 py-2.5 md:px-8">
          <h2 className="stamp-label">Screening policy</h2>
        </div>
        <div className="divide-y divide-rule-hair">
          <Row
            title="Blind screening"
            body="Redacts name, contact details, photograph, address, age and gender markers from every surface until a human decision is recorded. Evidence spans stay intact; only the identifying characters are masked."
            control={
              <Toggle
                checked={blind}
                onChange={setBlind}
                label="Blind screening"
              />
            }
          />
          <Row
            title="OCR fallback for scanned pages"
            body="Pages without a text layer are read optically. Low-confidence pages are reported as failures in the intake register rather than silently accepted."
            control={
              <Toggle
                checked={autoOcr}
                onChange={setAutoOcr}
                label="OCR fallback"
              />
            }
          />
          <Row
            title="Written reason required for every override"
            body="Cannot be disabled below the compliance floor. The reason is stored verbatim in the audit chain and is what an auditor reads first."
            control={
              <Toggle
                checked={requireReason}
                onChange={setRequireReason}
                disabled
                label="Require override reason"
              />
            }
          />
        </div>
      </section>

      <section className="border-t-2 border-rule-section bg-leaf">
        <div className="border-b border-rule-entry px-5 py-2.5 md:px-8">
          <h2 className="stamp-label">Register defaults</h2>
        </div>
        <div className="flex flex-wrap gap-4 px-5 py-4 md:px-8">
          <SelectField
            label="Interface language"
            defaultValue="en"
            className="w-56"
          >
            <option value="en">English</option>
            <option value="id">Bahasa Indonesia</option>
          </SelectField>
          <SelectField
            label="Retention period"
            defaultValue="18"
            className="w-56"
          >
            <option value="12">12 months</option>
            <option value="18">18 months</option>
            <option value="24">24 months</option>
          </SelectField>
          <TextField
            label="Audit export recipient"
            defaultValue="compliance@example.invalid"
            className="w-72"
            hint="Signed exports are delivered here weekly."
          />
        </div>
        <p className="flex items-start gap-1.5 border-t border-rule-entry px-5 py-3 text-xs text-ink-2 md:px-8">
          <Icon name="alert" size={13} className="mt-0.5 shrink-0 text-ochre" />
          No setting in this product can enable automatic rejection, automatic
          advancement, or inference of personality, culture fit or protected
          characteristics. Those capabilities do not exist in the system.
        </p>
      </section>
    </>
  );
}
