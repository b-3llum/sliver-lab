import { useEffect, useState } from "react";
import { api } from "@/api";
import type { LootInfo } from "@/types";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { CardList, DataCard } from "@/components/ui/DataCard";
import { EmptyState } from "@/components/ui/EmptyState";

export function Loot() {
  const [rows, setRows] = useState<LootInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<LootInfo[]>("/api/loot")
      .then((r) => { setRows(r); setErr(null); })
      .catch((e: any) => setErr(e.message));
  }, []);

  return (
    <div>
      <PageHeader
        title="Loot"
        count={rows.length}
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />
      <Card>
      <CardContent className="!p-0">
        {rows.length === 0 && (
          <EmptyState icon={ShieldAlert} title="no loot captured yet" description="Nothing in the loot store." />
        )}
        {/* mobile: cards */}
        <CardList>
          {rows.map((l) => (
            <DataCard
              key={l.ID}
              title={l.name}
              rows={[
                ["type", l.type],
                ["file", l.file_type],
                ["credential", l.credential_type],
                ["id", l.ID],
              ]}
            />
          ))}
        </CardList>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead><TR><TH>name</TH><TH>type</TH><TH>file</TH><TH>credential</TH><TH>id</TH></TR></THead>
          <TBody>
            {rows.map((l) => (
              <TR key={l.ID}>
                <TD>{l.name}</TD>
                <TD>{l.type}</TD>
                <TD className="text-muted">{l.file_type}</TD>
                <TD>{l.credential_type}</TD>
                <TD className="text-muted text-[10px]">{l.ID}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
      </Card>
    </div>
  );
}
