import { useEffect, useState } from "react";
import { api } from "@/api";
import { bus } from "@/ws";
import type { JobInfo } from "@/types";
import { Layers } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { CardList, DataCard } from "@/components/ui/DataCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";

export function Jobs() {
  const [rows, setRows] = useState<JobInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try { setRows(await api.get<JobInfo[]>("/api/jobs")); setErr(null); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => bus.subscribe((e) => { if (e.type.startsWith("job")) refresh(); }), []);

  async function kill(id: number) {
    try { await api.del(`/api/jobs/${id}`); await refresh(); }
    catch (e: any) { setErr(e.message); }
  }

  return (
    <div>
      <PageHeader
        title="Jobs"
        count={rows.length}
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />
      <Card>
      <CardContent className="!p-0">
        {rows.length === 0 && (
          <EmptyState icon={Layers} title="No jobs" description="No background jobs are running." />
        )}
        {/* mobile: cards */}
        <CardList>
          {rows.map((j) => (
            <DataCard
              key={j.ID}
              title={`${j.name} (#${j.ID})`}
              rows={[
                ["desc", j.description],
                ["proto", j.protocol],
                ["port", j.port],
              ]}
              actions={<Button variant="danger" size="sm" onClick={() => kill(j.ID)}>kill</Button>}
            />
          ))}
        </CardList>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead><TR><TH>id</TH><TH>name</TH><TH>desc</TH><TH>proto</TH><TH>port</TH><TH></TH></TR></THead>
          <TBody>
            {rows.map((j) => (
              <TR key={j.ID}>
                <TD>{j.ID}</TD>
                <TD>{j.name}</TD>
                <TD className="text-muted">{j.description}</TD>
                <TD>{j.protocol}</TD>
                <TD>{j.port}</TD>
                <TD className="text-right">
                  <Button variant="danger" size="sm" onClick={() => kill(j.ID)}>kill</Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
      </Card>
    </div>
  );
}
