import React, { useCallback, useEffect, useState } from "react";
import AppSidebar from "@/components/AppSidebar";
import RiskBadge from "@/components/RiskBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api from "@/lib/api";
import { toast } from "sonner";

const PAGE_SIZE = 25;

export default function Admin() {
  const [overview, setOverview] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [accountTotal, setAccountTotal] = useState(0);
  const [accountOffset, setAccountOffset] = useState(0);
  const [accountSearch, setAccountSearch] = useState("");
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historySearch, setHistorySearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [neo4jConnected, setNeo4jConnected] = useState(false);
  const [semanticReady, setSemanticReady] = useState(null);

  const loadOverview = useCallback(async () => {
    const { data } = await api.get("/admin/overview");
    setOverview(data);
  }, []);

  const loadAccounts = useCallback(async (search, offset) => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get("/admin/accounts", {
        params: { search, offset, limit: PAGE_SIZE },
      });
      setAccounts(data.items || []);
      setAccountTotal(data.total || 0);
      setAccountOffset(data.offset || 0);
    } catch (requestError) {
      const message = requestError?.response?.data?.detail || "Could not load account usage.";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async (account, search, offset) => {
    if (!account) return;
    setHistoryLoading(true);
    try {
      const { data } = await api.get(`/admin/accounts/${encodeURIComponent(account.user_id)}/history`, {
        params: { search, offset, limit: PAGE_SIZE },
      });
      setSelectedAccount(data.account);
      setHistory(data.items || []);
      setHistoryTotal(data.total || 0);
      setHistoryOffset(data.offset || 0);
    } catch (requestError) {
      toast.error(requestError?.response?.data?.detail || "Could not load this account's query history.");
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOverview().catch(requestError => {
      const message = requestError?.response?.data?.detail || "Could not load administrator analytics.";
      setError(message);
      toast.error(message);
    });
    loadAccounts("", 0);
  }, [loadOverview, loadAccounts]);

  useEffect(() => {
    api.get("/neo4j/status").then(response => {
      const connected = response.data.connected === true;
      setNeo4jConnected(connected);
      setSemanticReady(connected && response.data.semantic_search?.ready === true);
    }).catch(() => {
      setNeo4jConnected(false);
      setSemanticReady(null);
    });
  }, []);

  const searchAccounts = event => {
    event.preventDefault();
    setSelectedAccount(null);
    setHistory([]);
    setAccountOffset(0);
    loadAccounts(accountSearch.trim(), 0);
  };

  const searchHistory = event => {
    event.preventDefault();
    setHistoryOffset(0);
    loadHistory(selectedAccount, historySearch.trim(), 0);
  };

  const moveAccounts = offset => loadAccounts(accountSearch, offset);
  const moveHistory = offset => loadHistory(selectedAccount, historySearch, offset);
  const riskCounts = overview?.risk_distribution || { LOW: 0, MEDIUM: 0, HIGH: 0 };

  return (
    <div className="h-screen flex bg-[#04090A] text-[#E2F1F8] noise-overlay" data-testid="admin-page">
      <AppSidebar neo4jConnected={neo4jConnected} semanticReady={semanticReady} />
      <main className="flex-1 overflow-y-auto aegis-scrollbar p-8">
        <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">administration</div>
        <h1 className="font-display text-3xl mb-1">Account activity</h1>
        <p className="text-[#8D9A9F] text-sm mb-6 max-w-3xl">
          Read-only view of accounts with recorded use, their query histories, and risk analytics.
          Query text and generated summaries may contain sensitive information; access is restricted to administrators.
        </p>

        {error && (
          <div className="glass border border-[#FF3366]/30 p-4 mb-6 text-sm text-[#FF8AA5]" role="alert">
            {error}
          </div>
        )}

        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-5">
          <Stat label="accounts with history" value={overview?.accounts_with_history ?? "—"} />
          <Stat label="total queries" value={overview?.total_queries ?? "—"} />
          <Stat label="average risk score" value={Number.isFinite(overview?.average_risk_score) ? overview.average_risk_score.toFixed(2) : "—"} />
          <Stat label="latest activity" value={overview?.latest_activity ? new Date(overview.latest_activity).toLocaleDateString() : "—"} />
        </div>

        <section className="glass p-5 mb-6" data-testid="admin-risk-analytics">
          <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">cross-account analytics</div>
          <h2 className="font-display text-xl mb-4">Query risk distribution</h2>
          <div className="grid sm:grid-cols-3 gap-3">
            <Stat label="low risk" value={riskCounts.LOW} tone="green" />
            <Stat label="medium risk" value={riskCounts.MEDIUM} tone="amber" />
            <Stat label="high risk" value={riskCounts.HIGH} tone="danger" />
          </div>
          <p className="text-[11px] text-[#56646A] mt-3">
            Risk counts are behavioral assessments; disclosure level is evaluated independently for each query.
          </p>
        </section>

        <section className="glass p-5 mb-6" data-testid="admin-account-list">
          <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
            <div>
              <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">accounts</div>
              <h2 className="font-display text-xl">Accounts with query history</h2>
            </div>
            <form onSubmit={searchAccounts} className="flex gap-2">
              <Input
                value={accountSearch}
                onChange={event => setAccountSearch(event.target.value)}
                placeholder="Search name or email"
                className="w-64 bg-[#04090A] border-[#00F0FF]/15"
                data-testid="admin-account-search"
              />
              <Button type="submit" className="bg-[#00F0FF] text-[#04090A] hover:bg-[#00F0FF]/90">Search</Button>
            </form>
          </div>

          {loading ? (
            <p className="text-sm text-[#8D9A9F]">Loading account usage…</p>
          ) : accounts.length === 0 ? (
            <p className="text-sm text-[#8D9A9F]">No accounts with matching query history.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="font-mono-data uppercase tracking-widest text-[#56646A] border-b border-[#00F0FF]/10">
                  <tr>
                    <th className="py-2 pr-4 font-normal">Account</th>
                    <th className="py-2 px-3 font-normal">Role</th>
                    <th className="py-2 px-3 font-normal">Queries</th>
                    <th className="py-2 px-3 font-normal">Avg. risk</th>
                    <th className="py-2 px-3 font-normal">High risk</th>
                    <th className="py-2 px-3 font-normal">Last activity</th>
                    <th className="py-2 pl-3 font-normal">History</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map(account => (
                    <tr key={account.user_id} className="border-b border-[#00F0FF]/5 last:border-0">
                      <td className="py-3 pr-4">
                        <div className="text-[#E2F1F8]">{account.name || "Unnamed account"}</div>
                        <div className="text-[#8D9A9F] mt-1">{account.email}</div>
                      </td>
                      <td className="py-3 px-3 uppercase text-[#8D9A9F]">{account.role || "—"}</td>
                      <td className="py-3 px-3 font-mono-data">{account.query_count}</td>
                      <td className="py-3 px-3 font-mono-data">{Number(account.average_risk_score || 0).toFixed(2)}</td>
                      <td className="py-3 px-3 font-mono-data text-[#FF6484]">{account.risk_distribution?.HIGH || 0}</td>
                      <td className="py-3 px-3 text-[#8D9A9F] whitespace-nowrap">{account.latest_activity ? new Date(account.latest_activity).toLocaleString() : "—"}</td>
                      <td className="py-3 pl-3">
                        <Button
                          type="button"
                          variant="outline"
                          className="border-[#00F0FF]/25 hover:bg-[#00F0FF]/10"
                          onClick={() => {
                            setHistorySearch("");
                            loadHistory(account, "", 0);
                          }}
                        >
                          View
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager
            offset={accountOffset}
            total={accountTotal}
            pageSize={PAGE_SIZE}
            onPrevious={() => moveAccounts(Math.max(0, accountOffset - PAGE_SIZE))}
            onNext={() => moveAccounts(accountOffset + PAGE_SIZE)}
            label="accounts"
          />
        </section>

        {selectedAccount && (
          <section className="glass p-5" data-testid="admin-account-history">
            <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
              <div>
                <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">account history</div>
                <h2 className="font-display text-xl">{selectedAccount.name || selectedAccount.email}</h2>
                <p className="text-xs text-[#8D9A9F] mt-1">{selectedAccount.email} · role {selectedAccount.role || "—"}</p>
              </div>
              <form onSubmit={searchHistory} className="flex gap-2">
                <Input
                  value={historySearch}
                  onChange={event => setHistorySearch(event.target.value)}
                  placeholder="Search query text"
                  className="w-64 bg-[#04090A] border-[#00F0FF]/15"
                  data-testid="admin-history-search"
                />
                <Button type="submit" className="bg-[#00F0FF] text-[#04090A] hover:bg-[#00F0FF]/90">Search</Button>
              </form>
            </div>

            {historyLoading ? (
              <p className="text-sm text-[#8D9A9F]">Loading query history…</p>
            ) : history.length === 0 ? (
              <p className="text-sm text-[#8D9A9F]">No queries match this search.</p>
            ) : (
              <div className="space-y-3">
                {history.map(record => (
                  <article key={record.query_id} className="border border-[#00F0FF]/10 p-4" data-testid="admin-history-item">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <RiskBadge level={record.risk_level} score={record.adjusted ?? record.ewma} />
                        <span className="font-mono-data text-[10px] uppercase tracking-widest text-[#FFB347]">
                          disclosure {record.disclosure_level || record.risk_level}
                        </span>
                        {record.origin?.startsWith("simulator") && (
                          <span className="font-mono-data text-[10px] uppercase text-[#FF6484]">simulator</span>
                        )}
                      </div>
                      <span className="font-mono-data text-[10px] text-[#56646A]">
                        {record.created_at ? new Date(record.created_at).toLocaleString() : "—"} · {record.latency_ms ?? "—"}ms
                      </span>
                    </div>
                    <p className="text-sm text-[#E2F1F8] break-words">{record.query}</p>
                    {record.summary && <p className="text-xs text-[#8D9A9F] mt-2">{record.summary}</p>}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 font-mono-data text-[10px] text-[#8D9A9F]">
                      <span>score {Number(record.adjusted ?? record.ewma ?? 0).toFixed(2)}</span>
                      <span>disclosed records {record.disclosed_records_count}</span>
                      <span>answer confidence {Math.round((record.confidence || 0) * 100)}%</span>
                    </div>
                    {record.reasoning && <p className="text-[11px] text-[#8D9A9F] mt-2">{record.reasoning}</p>}
                    {record.hard_gate_reason && <p className="text-[11px] text-[#FFB347] mt-1">Risk override: {record.hard_gate_reason}</p>}
                  </article>
                ))}
              </div>
            )}
            <Pager
              offset={historyOffset}
              total={historyTotal}
              pageSize={PAGE_SIZE}
              onPrevious={() => moveHistory(Math.max(0, historyOffset - PAGE_SIZE))}
              onNext={() => moveHistory(historyOffset + PAGE_SIZE)}
              label="queries"
            />
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, tone = "teal" }) {
  const color = { teal: "#00F0FF", green: "#00E676", amber: "#FFB347", danger: "#FF3366" }[tone];
  return (
    <div className="glass p-4">
      <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">{label}</div>
      <div className="font-display text-2xl mt-1" style={{ color }}>{value}</div>
    </div>
  );
}

function Pager({ offset, total, pageSize, onPrevious, onNext, label }) {
  if (total <= pageSize) return null;
  const first = offset + 1;
  const last = Math.min(offset + pageSize, total);
  return (
    <div className="flex justify-end items-center gap-3 mt-4 text-xs text-[#8D9A9F]">
      <span>{first}–{last} of {total} {label}</span>
      <Button type="button" variant="outline" disabled={offset === 0} onClick={onPrevious} className="border-[#00F0FF]/20">Previous</Button>
      <Button type="button" variant="outline" disabled={offset + pageSize >= total} onClick={onNext} className="border-[#00F0FF]/20">Next</Button>
    </div>
  );
}
