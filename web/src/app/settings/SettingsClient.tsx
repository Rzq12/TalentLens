"use client";

import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock } from "@/components/ui/Seal";
import { useCurrentPrincipal } from "@/lib/hooks";

export default function SettingsClient() {
  const { data: principal, loading, error } = useCurrentPrincipal();

  return (
    <>
      <Masthead
        title="Settings"
        meta={
          <>
            <MetaFact
              label="Tenant"
              value={principal?.tenant_id ?? "Loading"}
              mono
            />
            <MetaFact
              label="User"
              value={principal?.user_id ?? "Loading"}
              mono
            />
            <MetaFact
              label="Role"
              value={principal?.roles.join(", ") ?? "Loading"}
            />
          </>
        }
        seal={
          <SealBlock
            tone="intact"
            label="Retention"
            value={
              loading ? "Loading" : error ? "Unavailable" : "Backend policy"
            }
            meta={error ? "Identity unavailable" : "Backend identity"}
          />
        }
      />

      <section className="border-t-2 border-rule-section bg-leaf px-5 py-8 md:px-8">
        {loading ? (
          <p className="text-sm text-ink-3">Loading backend identity...</p>
        ) : error ? (
          <p className="text-sm text-seal">
            Unable to load backend identity: {error.message}
          </p>
        ) : (
          <p className="text-sm text-ink-2">
            Account settings are managed by the backend identity provider.
          </p>
        )}
      </section>
    </>
  );
}
