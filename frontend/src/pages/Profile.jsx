import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import AppSidebar from "@/components/AppSidebar";
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, CartesianGrid } from "recharts";
import { useAuth } from "@/context/AuthContext";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export default function Profile() {
  const { user, setUser } = useAuth();
  const [data, setData] = useState(null);
  const [roles, setRoles] = useState([]);
  const [saving, setSaving] = useState(false);
  const [neo4jConnected, setNeo4jConnected] = useState(false);
  const [semanticReady, setSemanticReady] = useState(null);
  const [timeWindow, setTimeWindow] = useState("all");

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
    api.get("/risk-trend?limit=500").then(r => setData(r.data)).catch(() => setData({ series: [], distribution: { LOW: 0, MEDIUM: 0, HIGH: 0 }, count: 0, average_score: 0 }));
    api.get("/roles").then(r => setRoles(r.data.roles)).catch(() => {});
    refreshNeo4jStatus();
  }, []);

  const saveRole = async (role) => {
    setSaving(true);
    try {
      const { data } = await api.put("/me/role", { role });
      setUser(data);
      toast.success(`Role updated to ${role}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to update role");
    } finally { setSaving(false); }
  };

  const allSeries = data?.series || [];
  const windowMs = {
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
  }[timeWindow];
  const cutoff = windowMs ? Date.now() - windowMs : null;
  const visibleRecords = allSeries.filter(record => {
    if (cutoff === null) return true;
    const timestamp = Date.parse(record.created_at || "");
    return Number.isFinite(timestamp) && timestamp >= cutoff;
  });
  const series = visibleRecords.map((s, i) => ({
    idx: i + 1,
    ewma: s.ewma,
    adjusted: s.adjusted ?? s.ewma,
    composite: s.composite,
    level: s.risk_level,
    label: (s.query || "").slice(0, 40),
  }));
  const distribution = visibleRecords.reduce((counts, record) => {
    const level = record.risk_level;
    if (Object.prototype.hasOwnProperty.call(counts, level)) counts[level] += 1;
    return counts;
  }, { LOW: 0, MEDIUM: 0, HIGH: 0 });
  const scores = visibleRecords.map(record => record.adjusted ?? record.ewma).filter(Number.isFinite);
  const averageScore = scores.length
    ? scores.reduce((total, score) => total + score, 0) / scores.length
    : 0;
  const scoreChange = scores.length > 1 ? scores[scores.length - 1] - scores[0] : null;
  const latestRecord = visibleRecords[visibleRecords.length - 1];
  const latestSignals = latestRecord?.signals || {};
  const signalLabels = {
    semantic: "Query similarity",
    temporal: "Query frequency",
    entity: "Repeated entities",
    graph: "Retrieval breadth",
  };
  const drivers = Object.entries(signalLabels)
    .map(([key, label]) => ({
      key,
      label,
      score: Number(latestSignals[key] || 0),
      weight: Number(latestRecord?.weights?.[key] || 0),
    }))
    .sort((a, b) => (b.score * b.weight) - (a.score * a.weight));
  const latestDriver = drivers[0];
  const currentSession = data?.current_session || {};
  const privilegedRoles = new Set(["admin", "executive", "legal"]);
  const canManagePrivilegedRoles = privilegedRoles.has(user?.role);
  const selectableRoles = roles.filter(r =>
    r.id === user?.role ||
    (!privilegedRoles.has(r.id) || canManagePrivilegedRoles)
  );

  return (
    <div className="h-screen flex bg-[#04090A] text-[#E2F1F8] noise-overlay" data-testid="profile-page">
      <AppSidebar neo4jConnected={neo4jConnected} semanticReady={semanticReady} />
      <main className="flex-1 overflow-y-auto aegis-scrollbar p-8">
        <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">telemetry</div>
        <h1 className="font-display text-3xl mb-1">Your Risk Trend</h1>
        <p className="text-[#8D9A9F] text-sm mb-6">
          Adjusted privacy risk score across your most recent AegisGraph queries.
          Threshold bands mark the LOW / MEDIUM / HIGH transitions.
        </p>

        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <p className="text-xs text-[#8D9A9F]">
            Showing {visibleRecords.length} of the latest {allSeries.length} recorded queries
            {latestDriver ? ` · strongest latest signal: ${latestDriver.label}` : ""}
          </p>
          <div className="flex items-center gap-2">
            <span className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">time range</span>
            <Select value={timeWindow} onValueChange={setTimeWindow}>
              <SelectTrigger className="w-40 bg-[#04090A] border-[#00F0FF]/20" data-testid="risk-trend-window">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0B1215] border-[#00F0FF]/30 text-[#E2F1F8]">
                <SelectItem value="all">All loaded</SelectItem>
                <SelectItem value="24h">Last 24 hours</SelectItem>
                <SelectItem value="7d">Last 7 days</SelectItem>
                <SelectItem value="30d">Last 30 days</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="grid md:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
          <Stat label="queries"     value={visibleRecords.length} tone="teal" />
          <Stat label="avg. score"  value={averageScore.toFixed(2)} tone="teal" />
          <Stat label="low"         value={distribution.LOW}    tone="green" />
          <Stat label="medium"      value={distribution.MEDIUM} tone="amber" />
          <Stat label="high"        value={distribution.HIGH}   tone="danger" />
          <Stat
            label="score change"
            value={scoreChange === null ? "—" : `${scoreChange > 0 ? "+" : ""}${scoreChange.toFixed(2)}`}
            tone={scoreChange === null ? "teal" : scoreChange > 0.02 ? "danger" : scoreChange < -0.02 ? "green" : "teal"}
          />
        </div>

        <div className="glass p-4 h-80" data-testid="risk-trend-chart">
          {series.length === 0 ? (
            <div className="h-full grid place-items-center text-[#56646A] font-mono-data text-xs">
              run a few queries to see your risk trend
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                <CartesianGrid stroke="rgba(0,240,255,0.08)" strokeDasharray="2 2" />
                <XAxis dataKey="idx" stroke="#56646A" fontSize={10} tickLine={false} />
                <YAxis domain={[0, 1]} stroke="#56646A" fontSize={10} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: "#0B1215", border: "1px solid rgba(0,240,255,0.3)", fontSize: 12 }}
                  labelFormatter={(v) => `query #${v}`}
                />
                <ReferenceLine y={0.35} stroke="#00E676" strokeDasharray="3 3" label={{ value: "LOW/MED", fill: "#00E676", fontSize: 10, position: "insideTopRight" }} />
                <ReferenceLine y={0.65} stroke="#FF3366" strokeDasharray="3 3" label={{ value: "MED/HIGH", fill: "#FF3366", fontSize: 10, position: "insideTopRight" }} />
                <Line type="monotone" dataKey="adjusted"  stroke="#00F0FF" strokeWidth={2} dot={{ r: 3, fill: "#00F0FF" }} name="Adjusted score" />
                <Line type="monotone" dataKey="ewma"      stroke="#FFB347" strokeWidth={1.5} strokeDasharray="4 3" dot={false} name="EWMA score" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="grid lg:grid-cols-2 gap-4 mt-6">
          <section className="glass p-5" data-testid="risk-drivers-panel">
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">risk signals</div>
            <h2 className="font-display text-xl mb-1">Latest query indicators</h2>
            <p className="text-xs text-[#8D9A9F] mb-4">
              Signal values are 0–1; weights show each signal’s configured share in the score.
            </p>
            {latestRecord ? (
              <>
                <p className="text-sm text-[#C4D1D6] mb-4 break-words">{latestRecord.query}</p>
                <div className="space-y-3">
                  {drivers.map(driver => (
                    <div key={driver.key}>
                      <div className="flex justify-between gap-3 text-xs mb-1">
                        <span className="text-[#C4D1D6]">{driver.label}</span>
                        <span className="font-mono-data text-[#8D9A9F]">
                          {driver.score.toFixed(2)} · weight {(driver.weight * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="h-1.5 bg-[#172327] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#00F0FF] rounded-full"
                          style={{ width: `${Math.max(0, Math.min(100, driver.score * 100))}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                {latestRecord.reasoning && (
                  <p className="mt-4 pt-3 border-t border-[#00F0FF]/10 text-xs text-[#8D9A9F]">
                    Assessment: {latestRecord.reasoning}
                  </p>
                )}
                {latestRecord.hard_gate_reason && (
                  <p className="mt-2 text-xs text-[#FFB347]">
                    High-risk override: {latestRecord.hard_gate_reason}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-[#8D9A9F]">No queries fall within this time range.</p>
            )}
          </section>

          <section className="glass p-5" data-testid="session-context-panel">
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">session context</div>
            <h2 className="font-display text-xl mb-1">Risk carry-over</h2>
            <p className="text-xs text-[#8D9A9F] mb-4">
              Behavioral scoring uses a session EWMA, so a prior query can influence later scores in this login.
            </p>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <Stat label="queries this login" value={currentSession.query_count ?? 0} tone="teal" />
              <Stat
                label="latest session score"
                value={Number.isFinite(currentSession.latest_score) ? currentSession.latest_score.toFixed(2) : "—"}
                tone={currentSession.latest_level === "HIGH" ? "danger" : currentSession.latest_level === "MEDIUM" ? "amber" : "green"}
              />
            </div>
            <p className="text-xs text-[#8D9A9F] leading-relaxed">
              Session carry-over resets when a new login session begins. Disclosure limits are evaluated separately for every query; a previous high-risk result does not permanently lock the account at HIGH.
            </p>
          </section>
        </div>

        <section className="mt-6 glass p-5" data-testid="recent-risk-details">
          <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">recent activity</div>
          <h2 className="font-display text-xl mb-4">Risk and disclosure by query</h2>
          {visibleRecords.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="font-mono-data uppercase tracking-widest text-[#56646A] border-b border-[#00F0FF]/10">
                  <tr>
                    <th className="py-2 pr-4 font-normal">Query</th>
                    <th className="py-2 px-3 font-normal">Risk</th>
                    <th className="py-2 px-3 font-normal">Disclosure</th>
                    <th className="py-2 px-3 font-normal">Records disclosed</th>
                    <th className="py-2 pl-3 font-normal">When</th>
                  </tr>
                </thead>
                <tbody>
                  {[...visibleRecords].reverse().slice(0, 10).map((record, index) => (
                    <tr key={`${record.created_at}-${index}`} className="border-b border-[#00F0FF]/5 last:border-0">
                      <td className="py-3 pr-4 text-[#C4D1D6] max-w-md truncate" title={record.query}>{record.query}</td>
                      <td className="py-3 px-3"><RiskBadge level={record.risk_level} /></td>
                      <td className="py-3 px-3"><RiskBadge level={record.disclosure_level || record.risk_level} /></td>
                      <td className="py-3 px-3 font-mono-data text-[#8D9A9F]">{record.disclosed_records_count ?? 0}</td>
                      <td className="py-3 pl-3 text-[#8D9A9F] whitespace-nowrap">
                        {record.created_at ? new Date(record.created_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-[#8D9A9F]">No queries fall within this time range.</p>
          )}
          <p className="mt-3 text-[11px] text-[#56646A]">
            Record counts reflect only data disclosed to you after moderation, not all matched graph records.
          </p>
        </section>

        <section className="mt-8 glass p-5 max-w-2xl" data-testid="role-panel">
          <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-1">identity</div>
          <h2 className="font-display text-xl mb-3">Your organisational role</h2>
          <p className="text-[13px] text-[#8D9A9F] leading-relaxed mb-4">
            The privacy layer adds a role-aware monitoring bias to every risk
            score. External users receive +0.15, employees receive +0.00,
            executive and legal receive +0.05, and administrators receive
            +0.00 with clearance 5. Clearance is role metadata, not a grant to
            bypass query risk or disclosure safeguards; role bias does not
            grant or remove authorization. Privileged roles must be assigned
            by an administrator and cannot be self-selected.
          </p>
          <div className="flex items-center gap-3">
            <Select value={user?.role || "external"} onValueChange={saveRole} disabled={saving}>
              <SelectTrigger className="w-64 bg-[#04090A] border-[#00F0FF]/20" data-testid="role-select-trigger">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0B1215] border-[#00F0FF]/30 text-[#E2F1F8]">
                {selectableRoles.map(r => (
                  <SelectItem key={r.id} value={r.id} data-testid={`role-option-${r.id}`}>
                    <span className="mr-3">{r.label}</span>
                    <span className="font-mono-data text-[10px] text-[#8D9A9F]">
                      clearance {r.clearance} · bias {r.risk_adjustment >= 0 ? "+" : ""}{r.risk_adjustment.toFixed(2)}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {user?.linked_employee && (
              <div className="font-mono-data text-[11px] text-[#00E676]">
                linked to Enron employee record
              </div>
            )}
          </div>
        </section>

        {user && (
          <div className="mt-6 text-[12px] font-mono-data text-[#56646A]">
            signed in as {user.email}
          </div>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, tone }) {
  const color = { teal: "#00F0FF", green: "#00E676", amber: "#FFB347", danger: "#FF3366" }[tone] || "#00F0FF";
  return (
    <div className="glass p-4" data-testid={`stat-${label.replace(/\s+/g,'-')}`}>
      <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">{label}</div>
      <div className="font-display text-3xl mt-1" style={{ color }}>{value}</div>
    </div>
  );
}

function RiskBadge({ level }) {
  const colors = {
    LOW: "#00E676",
    MEDIUM: "#FFB347",
    HIGH: "#FF3366",
  };
  const color = colors[level] || "#8D9A9F";
  return (
    <span
      className="font-mono-data uppercase text-[10px] tracking-wider"
      style={{ color }}
    >
      {level || "UNKNOWN"}
    </span>
  );
}
