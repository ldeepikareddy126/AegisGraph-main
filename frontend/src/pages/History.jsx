import React, { useEffect, useState } from "react";
import api, { API_BASE } from "@/lib/api";
import AppSidebar from "@/components/AppSidebar";
import RiskBadge from "@/components/RiskBadge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { DownloadSimple, MagnifyingGlass } from "@phosphor-icons/react";

export default function History() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [neo4jConnected, setNeo4jConnected] = useState(false);
  const [semanticReady, setSemanticReady] = useState(null);

  const load = async (q = "") => {
    setLoading(true);
    try {
      const { data } = await api.get("/history", { params: { search: q, limit: 200 } });
      setItems(data.items);
    } finally { setLoading(false); }
  };

  const refreshNeo4jStatus = () =>
    api.get("/neo4j/status")
      .then(r => {
        const connected = r.data.connected === true;
        setNeo4jConnected(connected);
        setSemanticReady(connected && r.data.semantic_search?.ready === true);
      })
      .catch(() => {
        setNeo4jConnected(false);
        setSemanticReady(null);
      });

  useEffect(() => {
    load();
    refreshNeo4jStatus();
  }, []);

  const onSearch = (e) => {
    e.preventDefault();
    load(search.trim());
  };

  return (
    <div className="h-screen flex bg-[#04090A] text-[#E2F1F8] noise-overlay" data-testid="history-page">
      <AppSidebar neo4jConnected={neo4jConnected} semanticReady={semanticReady} />
      <main className="flex-1 overflow-y-auto aegis-scrollbar p-8">
        <div className="flex items-start justify-between flex-wrap gap-4 mb-6">
          <div>
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">activity</div>
            <h1 className="font-display text-3xl">Query History</h1>
            <p className="text-[#8D9A9F] text-sm">All AegisGraph queries you have run.  Search across text, or export the audit trail as CSV.</p>
          </div>
          <a
            href={`${API_BASE}/history/export`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 border border-[#00F0FF]/30 text-[13px] hover:border-[#00F0FF] transition-colors"
            style={{ transition: "border-color 0.2s ease" }}
            data-testid="export-csv-btn"
          >
            <DownloadSimple size={14} weight="bold" /> Export CSV
          </a>
        </div>

        <form onSubmit={onSearch} className="flex items-center gap-2 mb-4">
          <div className="relative flex-1 max-w-xl">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#56646A]" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search your history…"
              className="bg-[#0B1215] border-[#00F0FF]/15 pl-9"
              data-testid="history-search-input"
            />
          </div>
          <Button type="submit" className="bg-[#00F0FF] text-[#04090A] hover:bg-[#00F0FF]/90" data-testid="history-search-btn">
            Search
          </Button>
        </form>

        {loading ? (
          <div className="text-[#8D9A9F] font-mono-data text-sm">loading…</div>
        ) : items.length === 0 ? (
          <div className="text-[#8D9A9F]">No results.</div>
        ) : (
          <div className="space-y-3">
            {items.map((it, i) => (
              <div key={it.query_id} className="glass p-4" data-testid={`history-item-${i}`}>
                <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                  <div className="flex items-center gap-2">
                    <RiskBadge level={it.risk_level} score={it.adjusted ?? it.ewma} />
                    <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#FFB347]/25 text-[#FFB347]">
                      disclosure {it.disclosure_level || it.risk_level}
                    </span>
                    {it.origin?.startsWith("simulator") && (
                      <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#FF3366]/30 text-[#FF3366] bg-[#FF3366]/[0.04]">
                        red team
                      </span>
                    )}
                  </div>
                  <span className="font-mono-data text-[10px] text-[#56646A]">
                    {new Date(it.created_at).toLocaleString()} · {it.latency_ms}ms · role {it.role || "—"}
                  </span>
                </div>
                <div className="text-[14px] text-[#E2F1F8] mb-1 font-medium">{it.query}</div>
                <div className="text-[13px] text-[#E2F1F8]/70 line-clamp-2">{it.summary}</div>
                <div className="mt-2 font-mono-data text-[11px] text-[#8D9A9F]">
                  disclosed {it.matched_emails_count} record(s) · confidence {Math.round((it.confidence || 0) * 100)}%
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
