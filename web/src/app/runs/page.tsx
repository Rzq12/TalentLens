import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock } from "@/components/ui/Seal";
import { SyntheticNotice } from "@/components/ui/Section";
import { RunMonitor } from "@/components/run/RunMonitor";
import { RUN } from "@/lib/demo";
import { Button } from "@/components/ui/Button";

export const metadata = { title: "Screening run — TalentLens" };

export default function RunsPage() {
  return (
    <>
      <Masthead
        crumbs={[{ label: "Screening runs", href: "/runs" }, { label: RUN.id }]}
        title={RUN.jobTitle}
        meta={
          <>
            <MetaFact label="Run" value={RUN.id} mono />
            <MetaFact label="Rubric" value={RUN.rubricVersion} mono />
            <MetaFact label="Opened" value={RUN.startedAt} mono />
          </>
        }
        seal={
          <SealBlock
            tone="pending"
            label="Run state"
            value="Running"
            meta="live"
          />
        }
        actions={
          <>
            <Button variant="ruled" icon="pause">
              Pause
            </Button>
            <Button variant="alarm" icon="stop">
              Abort
            </Button>
          </>
        }
      />
      <SyntheticNotice />
      <RunMonitor />
    </>
  );
}
