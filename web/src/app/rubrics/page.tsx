import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock } from "@/components/ui/Seal";
import { SyntheticNotice } from "@/components/ui/Section";
import { RubricEditor } from "@/components/rubric/RubricEditor";

export const metadata = { title: "Rubric editor — TalentLens" };

export default function RubricsPage() {
  return (
    <>
      <Masthead
        crumbs={[
          { label: "Jobs", href: "/jobs" },
          { label: "Senior Frontend Engineer", href: "/jobs" },
          { label: "Rubric REQ-8992" },
        ]}
        title="Screening rubric"
        meta={
          <>
            <MetaFact label="Rubric" value="REQ-8992" mono />
            <MetaFact label="Working copy" value="v5 draft" mono />
            <MetaFact label="Autosaved" value="15:21:08" mono />
          </>
        }
        seal={
          <SealBlock
            tone="draft"
            label="Seal"
            value="Unsealed draft"
            meta="editable"
          />
        }
      />
      <SyntheticNotice />
      <RubricEditor />
    </>
  );
}
