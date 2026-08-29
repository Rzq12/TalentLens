import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock, Seal } from "@/components/ui/Seal";
import { Button } from "@/components/ui/Button";
import { SettingsForm } from "@/components/settings/SettingsForm";

export const metadata = { title: "Settings — TalentLens" };

const VERSIONS = [
  { label: "Model", value: "gpt-4o-2026-05-13" },
  { label: "Prompt set", value: "req-eval@2.4.1" },
  { label: "Embeddings", value: "text-embed-3-lg" },
  { label: "Aggregator", value: "deterministic-py@1.3" },
];

export default function SettingsPage() {
  return (
    <>
      <Masthead
        title="Settings"
        meta={
          <>
            <MetaFact label="Tenant" value="demo" mono />
            <MetaFact label="Region" value="eu-central" mono />
            <MetaFact label="Role" value="recruiter" mono />
          </>
        }
        seal={
          <SealBlock
            tone="intact"
            label="Retention"
            value="18 months"
            meta="GDPR Art. 17"
          />
        }
        actions={
          <Button variant="stamp" icon="check">
            Save changes
          </Button>
        }
      />

      <SettingsForm />

      <section className="border-t-2 border-rule-section bg-leaf">
        <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
          <h2 className="stamp-label">Version stamps applied to every score</h2>
          <Seal tone="intact">Reproducible</Seal>
        </div>
        <dl className="grid grid-cols-1 divide-y divide-rule-hair sm:grid-cols-2 sm:divide-x xl:grid-cols-4 xl:divide-y-0">
          {VERSIONS.map((v, i) => (
            <div
              key={v.label}
              className={`px-5 py-3 md:px-8 ${i >= 2 ? "sm:border-t sm:border-rule-hair xl:border-t-0" : ""}`}
            >
              <dt className="stamp-label">{v.label}</dt>
              <dd className="mt-0.5 font-mono text-sm text-ink">{v.value}</dd>
            </div>
          ))}
        </dl>
        <p className="border-t border-rule-entry px-5 py-3 text-xs text-ink-2 md:px-8">
          Changing any of these starts a new version line. Existing assessments
          keep the versions they were produced under, so an auditor can
          reconstruct any score exactly as it was computed.
        </p>
      </section>
    </>
  );
}
