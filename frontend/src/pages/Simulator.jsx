import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import AppSidebar from "@/components/AppSidebar";
import RiskBadge from "@/components/RiskBadge";
import RetrievalPipeline from "@/components/RetrievalPipeline";
import KnowledgeGraph from "@/components/KnowledgeGraph";
import { useAuth } from "@/context/AuthContext";
import { motion } from "framer-motion";
import { Lock, LockKey, Play, CheckCircle, XCircle, ShieldWarning, ArrowsHorizontal } from "@phosphor-icons/react";
import { toast } from "sonner";
import CompareModal from "@/components/CompareModal";

const SEVERITY_STYLE = {
  info:     { border: "border-[#00E676]/30", text: "text-[#00E676]" },
  medium:   { border: "border-[#FFB347]/30", text: "text-[#FFB347]" },
  high:     { border: "border-[#FFB347]/40", text: "text-[#FFB347]" },
  critical: { border: "border-[#FF3366]/40", text: "text-[#FF3366]" },
};

export default function Simulator() {
  const { user } = useAuth();
  const [access, setAccess] = useState(null);          // {allowed, role, allowed_roles}
  const [scenarios, setScenarios] = useState([]);
  const [accessError, setAccessError] = useState("");
  const [scenariosError, setScenariosError] = useState("");
  const [loadingScenarios, setLoadingScenarios] = useState(false);
  const [running, setRunning] = useState(null);        // scenario_id being run
  const [results, setResults] = useState({});          // {scenario_id: response}
  const [selected, setSelected] = useState(null);      // scenario_id shown in detail pane
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareScenario, setCompareScenario] = useState(null);
  const [neo4jConnected, setNeo4jConnected] = useState(false);
  const [semanticReady, setSemanticReady] = useState(null);

  const refreshNeo4jStatus = useCallback(() =>
    api.get("/neo4j/status")
      .then(r => {
        const connected = r.data.connected === true;
        setNeo4jConnected(connected);
        setSemanticReady(connected && r.data.semantic_search?.ready === true);
      })
      .catch(() => {
        setNeo4jConnected(false);
        setSemanticReady(null);
      }), []);

  const loadAccess = useCallback(async () => {
    setAccessError("");
    setAccess(null);
    try {
      const { data } = await api.get("/simulator/access");
      setAccess(data);
    } catch (error) {
      const status = error?.response?.status;
      setAccessError(status === 401
        ? "Your application session is no longer authenticated. Sign out, sign back in, then reopen the simulator."
        : error?.response?.data?.detail || "Could not verify simulator access. Check the backend connection and retry.");
    }
  }, []);

  const loadScenarios = useCallback(async () => {
    setLoadingScenarios(true);
    setScenariosError("");
    try {
      const { data } = await api.get("/simulator/scenarios");
      setScenarios(data.scenarios || []);
    } catch (error) {
      const status = error?.response?.status;
      setScenariosError(status === 401
        ? "Your application session expired. Sign out and sign back in to continue."
        : status === 403
          ? "Your role no longer has simulator access. Refresh your session or ask an administrator to verify your role."
          : error?.response?.data?.detail || "Could not load simulator scenarios. Check the backend connection and retry.");
    } finally {
      setLoadingScenarios(false);
    }
  }, []);

  useEffect(() => {
    loadAccess();
    refreshNeo4jStatus();
  }, [loadAccess, refreshNeo4jStatus]);

  useEffect(() => {
    if (access?.allowed) loadScenarios();
  }, [access?.allowed, loadScenarios]);

  const runOne = async (id) => {
    setRunning(id);
    setSelected(id);
    try {
      const { data } = await api.post("/simulator/run", { scenario_id: id });
      setResults(prev => ({ ...prev, [id]: data }));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Simulator run failed");
    } finally {
      setRunning(null);
    }
  };

  const runAll = async () => {
    for (const s of scenarios) {
      /* sequential so the pipeline animates step by step */
      await runOne(s.id);
    }
  };

  const passed = scenarios.filter(s => results[s.id]?.evaluation?.passed).length;
  const total  = scenarios.filter(s => results[s.id]).length;

  return (
    <div className="h-screen flex bg-[#04090A] text-[#E2F1F8] noise-overlay" data-testid="simulator-page">
      <AppSidebar neo4jConnected={neo4jConnected} semanticReady={semanticReady} />
      <main className="flex-1 overflow-y-auto aegis-scrollbar p-8">
        <div className="flex items-start justify-between flex-wrap gap-3 mb-6">
          <div>
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#FF3366] mb-1 flex items-center gap-2">
              <ShieldWarning size={12} weight="fill" /> red team · restricted
            </div>
            <h1 className="font-display text-3xl">Attack Simulator</h1>
            <p className="text-[#8D9A9F] text-sm max-w-2xl">
              A curated set of adversarial prompts. Each run executes AegisGraph's
              full pipeline against your session so the moderation layer's response
              can be demonstrated in real time.
            </p>
          </div>
          {access?.allowed && (
            <div className="flex items-center gap-3">
              {total > 0 && (
                <div className="glass px-4 py-2 font-mono-data text-[11px]">
                  <span className="text-[#8D9A9F] uppercase tracking-widest">mitigated</span>{" "}
                  <span className="text-[#E2F1F8]">{passed}/{total}</span>
                </div>
              )}
              <button
                onClick={() => { setCompareScenario(scenarios[1] || scenarios[0]); setCompareOpen(true); }}
                disabled={!scenarios.length}
                data-testid="simulator-compare-btn"
                className="inline-flex items-center gap-2 px-4 py-2 border border-[#00F0FF]/30 text-[13px] text-[#E2F1F8] hover:border-[#00F0FF] disabled:opacity-40 transition-colors"
                style={{ transition: "border-color 0.2s ease" }}
              >
                <ArrowsHorizontal size={14} weight="bold" /> Compare roles
              </button>
              <button
                onClick={runAll}
                disabled={!!running}
                data-testid="simulator-run-all-btn"
                className="inline-flex items-center gap-2 px-4 py-2 bg-[#00F0FF] text-[#04090A] text-[13px] hover:bg-[#00F0FF]/90 disabled:opacity-50 transition-colors"
                style={{ transition: "background-color 0.2s ease" }}
              >
                <Play size={14} weight="fill" /> Run all
              </button>
            </div>
          )}
        </div>

        {access === null && (
          <div className="glass p-4 text-sm text-[#8D9A9F]" role={accessError ? "alert" : "status"}>
            {accessError || "checking access…"}
            {accessError && (
              <button
                type="button"
                onClick={loadAccess}
                className="ml-3 border border-[#00F0FF]/30 px-3 py-1 text-[#00F0FF] hover:border-[#00F0FF]"
              >
                Retry
              </button>
            )}
          </div>
        )}

        {access && !access.allowed && (
          <LockedCard role={access.role} allowedRoles={access.allowed_roles || []} />
        )}

        {access?.allowed && (
          <div className="grid lg:grid-cols-[minmax(0,1fr)_420px] gap-6">
            <div className="space-y-3">
              {scenariosError && (
                <div className="glass border border-[#FF3366]/30 p-4 text-sm text-[#FF8AA5]" role="alert">
                  {scenariosError}
                  <button
                    type="button"
                    onClick={loadScenarios}
                    disabled={loadingScenarios}
                    className="ml-3 border border-[#00F0FF]/30 px-3 py-1 text-[#00F0FF] hover:border-[#00F0FF] disabled:opacity-50"
                  >
                    {loadingScenarios ? "Retrying…" : "Retry"}
                  </button>
                </div>
              )}
              {loadingScenarios && scenarios.length === 0 && (
                <div className="text-[#56646A] font-mono-data text-xs" role="status">loading simulator scenarios…</div>
              )}
              {scenarios.map((s, i) => {
                const style = SEVERITY_STYLE[s.severity] || SEVERITY_STYLE.info;
                const res = results[s.id];
                const isRunning = running === s.id;
                return (
                  <motion.button
                    key={s.id}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    onClick={() => { setSelected(s.id); if (!res) runOne(s.id); }}
                    disabled={isRunning}
                    data-testid={`scenario-card-${s.id}`}
                    className={`text-left w-full glass p-4 border ${style.border} hover:border-opacity-100 transition-colors`}
                    style={{ transition: "border-color 0.2s ease, background-color 0.2s ease" }}
                  >
                    <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono-data text-[10px] uppercase tracking-widest ${style.text}`}>
                          {s.severity}
                        </span>
                        <span className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">
                          {s.category}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        {res && (
                          <>
                            <RiskBadge level={res.risk.level} score={res.risk.score} />
                            <span className="font-mono-data text-[9px] uppercase text-[#FFB347]">
                              disclose {res.moderation.disclosure_level}
                            </span>
                            {res.evaluation?.passed ? (
                              <CheckCircle size={16} weight="fill" className="text-[#00E676]" />
                            ) : (
                              <XCircle size={16} weight="fill" className="text-[#FF3366]" />
                            )}
                          </>
                        )}
                      </div>
                    </div>
                    <div className="text-[14px] text-[#E2F1F8] font-medium">{s.title}</div>
                    <div className="text-[12px] text-[#8D9A9F] mt-1">{s.description}</div>
                    <div className="mt-2 flex items-center justify-between font-mono-data text-[10px] text-[#56646A]">
                      <span>expected · {s.expected_level}</span>
                      <span className="flex items-center gap-2">
                        <span>{isRunning ? "running…" : (res ? "click to inspect" : "click to run")}</span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(ev) => { ev.stopPropagation(); setCompareScenario(s); setCompareOpen(true); }}
                          onKeyDown={(ev) => { if (ev.key === "Enter") { ev.stopPropagation(); setCompareScenario(s); setCompareOpen(true); } }}
                          data-testid={`compare-scenario-${s.id}`}
                          className="inline-flex items-center gap-1 border border-[#00F0FF]/25 px-2 py-0.5 hover:border-[#00F0FF] transition-colors text-[#00F0FF] cursor-pointer"
                          style={{ transition: "border-color 0.2s ease" }}
                        >
                          <ArrowsHorizontal size={10} weight="bold" /> compare
                        </span>
                      </span>
                    </div>
                  </motion.button>
                );
              })}
            </div>

            <aside className="lg:sticky lg:top-0 lg:h-fit space-y-4">
              <div className="glass p-4">
                <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-2">pipeline</div>
                <RetrievalPipeline
                  steps={selected && results[selected]?.pipeline}
                  active={selected && results[selected] ? 6 : -1}
                />
              </div>
              {selected && results[selected] && (
                <ScenarioResult data={results[selected]} />
              )}
              {!selected && (
                <div className="glass p-4 text-[#56646A] text-xs font-mono-data">
                  select a scenario to run it and view the moderated response
                </div>
              )}
            </aside>
          </div>
        )}
      </main>
      <CompareModal
        open={compareOpen}
        onOpenChange={(v) => { setCompareOpen(v); if (!v) setCompareScenario(null); }}
        scenario={compareScenario}
      />
    </div>
  );
}

function LockedCard({ role, allowedRoles }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="glass p-8 max-w-2xl mt-6"
      data-testid="simulator-locked"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 grid place-items-center border border-[#FF3366]/40">
          <LockKey size={18} weight="duotone" className="text-[#FF3366]" />
        </div>
        <div>
          <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#FF3366]">access restricted</div>
          <div className="font-display text-xl">Attack Simulator is not enabled for your role</div>
        </div>
      </div>
      <p className="text-[13px] text-[#E2F1F8]/80 leading-relaxed">
        Adversarial prompts can trigger the privacy layer to disclose the shape
        of the retrieval. To prevent misuse, this feature is limited to
        privileged reviewers.
      </p>
      <div className="mt-4 grid sm:grid-cols-2 gap-3 text-[12px]">
        <div className="border border-[#00F0FF]/15 p-3">
          <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">your role</div>
          <div className="text-[#E2F1F8] mt-0.5">{role || "external"}</div>
        </div>
        <div className="border border-[#00F0FF]/15 p-3">
          <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A]">allowed roles</div>
          <div className="text-[#E2F1F8] mt-0.5">{allowedRoles.join(", ") || "legal, executive"}</div>
        </div>
      </div>
      <p className="mt-4 text-[12px] text-[#8D9A9F]">
        Switch your role from the <span className="text-[#00F0FF]">Risk Trend</span> page
        to demo this feature during the presentation.
      </p>
    </motion.div>
  );
}

function ScenarioResult({ data }) {
  const grade = data.evaluation || {};
  const graph = data.graph || { nodes: [], links: [] };
  return (
    <div className="glass p-4" data-testid="simulator-result">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-2">
          <RiskBadge level={data.risk.level} score={data.risk.score} />
          <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#FFB347]/25 text-[#FFB347]">
            disclosure {data.moderation.disclosure_level}
          </span>
          <span className={`font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border ${grade.passed ? "border-[#00E676]/40 text-[#00E676]" : "border-[#FF3366]/40 text-[#FF3366]"}`}>
            {grade.passed ? "mitigated" : "review"}
          </span>
        </div>
        <div className="font-mono-data text-[10px] text-[#56646A]">
          expected {data.scenario?.expected_level} · observed {data.risk.level}
        </div>
      </div>
      <div className="text-[13px] text-[#E2F1F8]/90 whitespace-pre-wrap">
        {data.answer.summary}
      </div>
      <section className="mt-4 border border-[#00F0FF]/15 bg-[#04090A]/70" data-testid="simulator-graph">
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[#00F0FF]/10">
          <div className="text-[10px] uppercase tracking-widest text-[#8D9A9F]">
            disclosed graph · {graph.nodes.length} nodes · {graph.links.length} links
          </div>
          {data.moderation.disclosure_level === "MEDIUM" && (
            <span className="text-[9px] font-mono-data text-[#FFB347]">identities anonymized</span>
          )}
        </div>
        {data.moderation.disclosure_level === "HIGH" ? (
          <div className="h-36 grid place-items-center px-4 text-center text-[11px] text-[#8D9A9F]">
            Graph details are withheld by HIGH disclosure policy.
          </div>
        ) : graph.nodes.length > 0 ? (
          <div className="h-52 relative">
            <KnowledgeGraph
              graph={graph}
              highlighted={data.retrieved?.highlighted_node_ids || []}
            />
          </div>
        ) : (
          <div className="h-36 grid place-items-center px-4 text-center text-[11px] text-[#8D9A9F]">
            No connected nodes were returned for the disclosed matching records.
          </div>
        )}
      </section>
      {data.moderation.redactions_applied?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {data.moderation.redactions_applied.map(r => (
            <span key={r} className="text-[10px] font-mono-data uppercase tracking-widest px-2 py-0.5 border border-[#FFB347]/30 text-[#FFB347] bg-[#FFB347]/5">
              {data.moderation.disclosure_level === "HIGH" ? "withheld" : "redacted"} · {r}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 text-[11px] font-mono-data text-[#8D9A9F]">
        <span className="uppercase tracking-widest text-[#56646A]">expected behaviour</span>{" "}
        {data.scenario?.expected_behavior}
      </div>
    </div>
  );
}
