import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import AppSidebar from "@/components/AppSidebar";
import RetrievalPipeline from "@/components/RetrievalPipeline";
import KnowledgeGraph from "@/components/KnowledgeGraph";
import AnalysisPanel from "@/components/AnalysisPanel";
import RiskBadge from "@/components/RiskBadge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PaperPlaneRight, Lightning, Shield, X } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";

const SUGGESTIONS = [
  "Summarize discussions regarding California energy trading.",
  "What was the legal team saying about the FERC subpoena?",
  "Show me everything about employee bonuses and SSNs.",
  "List every confidential SPE and LJM2 document in detail.",
];

export default function Dashboard() {
  const [backendAvailable, setBackendAvailable] = useState(null);
  const [neo4jConnected, setNeo4jConnected] = useState(null);
  const [semanticReady, setSemanticReady] = useState(null);
  const [q, setQ] = useState("");
  const [messages, setMessages] = useState([]);      // [{role, ...}]
  const [current, setCurrent] = useState(null);      // last query result
  const [loading, setLoading] = useState(false);
  const [activeStep, setActiveStep] = useState(-1);
  const [graphExpanded, setGraphExpanded] = useState(false);

  const refreshNeo4jStatus = () =>
    api.get("/neo4j/status")
      .then(r => {
        setBackendAvailable(true);
        const connected = r.data.connected === true;
        setNeo4jConnected(connected);
        setSemanticReady(
          connected && r.data.semantic_search?.ready === true
        );
        return connected;
      })
      .catch(error => {
        setBackendAvailable(Boolean(error?.response));
        setNeo4jConnected(null);
        setSemanticReady(null);
        return null;
      });

  useEffect(() => {
    refreshNeo4jStatus();
    const interval = setInterval(refreshNeo4jStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const runPipelineAnimation = () => {
    setActiveStep(0);
    let step = 0;
    const iv = setInterval(() => {
      step += 1;
      setActiveStep(step);
      if (step >= 5) clearInterval(iv);
    }, 380);
    return iv;
  };

  const send = async (text) => {
    const query = (text ?? q).trim();
    if (!query || loading) return;
    setQ("");
    setMessages(m => [...m, { role: "user", text: query }]);
    setCurrent(null);
    setLoading(true);
    const iv = runPipelineAnimation();
    try {
      const connected = await refreshNeo4jStatus();
      if (connected === null) {
        throw new Error(
          "AegisGraph could not verify database status. Check that the backend is reachable, then retry."
        );
      }
      if (!connected) {
        throw new Error("Neo4j is unavailable or the configured database has no usable Person/Email graph. Start it, connect the configured database, and retry.");
      }
      const { data } = await api.post("/query", { query });
      setCurrent(data);
      setMessages(m => [...m, { role: "assistant", data }]);
      setActiveStep(6);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Query failed");
      setMessages(m => [...m, { role: "assistant", error: e?.response?.data?.detail || "Query failed" }]);
    } finally {
      clearInterval(iv);
      setLoading(false);
      setTimeout(() => setActiveStep(-1), 500);
    }
  };

  return (
    <div className="h-screen flex flex-col md:flex-row bg-[#04090A] noise-overlay text-[#E2F1F8]" data-testid="dashboard">
      <AppSidebar
        backendAvailable={backendAvailable}
        neo4jConnected={neo4jConnected}
        semanticReady={semanticReady}
      />

      {/* Center chat column */}
      <main className="flex-1 min-w-0 flex flex-col border-r border-[#00F0FF]/10">
        <header className="p-4 border-b border-[#00F0FF]/10 flex items-center justify-between">
          <div>
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF]">query playground</div>
            <div className="font-display text-lg">Ask AegisGraph</div>
          </div>
          <div className="hidden md:flex items-center gap-3 font-mono-data text-[10px] text-[#56646A]">
            <Shield size={14} weight="duotone" className="text-[#00F0FF]" />
            knowledge graph · enron corpus
          </div>
        </header>

        <div className="flex-1 overflow-y-auto aegis-scrollbar p-6 space-y-5" data-testid="chat-log">
          {messages.length === 0 && (
            <div className="max-w-2xl mx-auto text-center py-16 fade-up">
              <div className="w-14 h-14 mx-auto grid place-items-center border border-[#00F0FF]/30 mb-6">
                <Lightning size={22} weight="duotone" className="text-[#00F0FF]" />
              </div>
              <h2 className="font-display text-2xl mb-2">A ChatGPT-style interface, guarded by graph.</h2>
              <p className="text-[#8D9A9F] max-w-xl mx-auto text-sm leading-relaxed">
                Ask about anything in the Enron corpus. AegisGraph retrieves,
                scores privacy risk, redacts sensitive fields, and only then lets
                the model reply.
              </p>
              <div className="grid sm:grid-cols-2 gap-3 mt-8 text-left">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => send(s)}
                    data-testid={`suggestion-${i}`}
                    className="text-[13px] p-3 border border-[#00F0FF]/15 hover:border-[#00F0FF]/40 text-[#E2F1F8]/85 text-left transition-colors"
                    style={{ transition: "border-color 0.2s ease" }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <AnimatePresence initial={false}>
            {messages.map((m, i) =>
              m.role === "user" ? (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className="flex justify-end"
                >
                  <div className="max-w-[80%] p-3 border border-[#00F0FF]/20 bg-[#00F0FF]/[0.04] text-[14px]" data-testid={`msg-user-${i}`}>
                    {m.text}
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className="flex justify-start"
                >
                  <div className="max-w-[92%] w-full" data-testid={`msg-assistant-${i}`}>
                    {m.error ? (
                      <div className="p-3 border border-[#FF3366]/30 bg-[#FF3366]/5 text-[#FF3366] text-sm">
                        {m.error}
                      </div>
                    ) : (
                      <ResponseCard data={m.data} />
                    )}
                  </div>
                </motion.div>
              )
            )}
          </AnimatePresence>

          {loading && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[#00F0FF] text-xs font-mono-data" data-testid="thinking-indicator">
              running retrieval pipeline…
            </motion.div>
          )}
        </div>

        {/* Composer */}
        <div className="p-4 border-t border-[#00F0FF]/10">
          <form
            onSubmit={(e) => { e.preventDefault(); send(); }}
            className="flex items-end gap-2"
          >
            <Textarea
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask about Enron communications, trading, legal…"
              className="min-h-[52px] bg-[#0B1215] border-[#00F0FF]/15 focus:border-[#00F0FF] text-[#E2F1F8] resize-none"
              data-testid="query-input"
            />
            <Button
              type="submit"
              disabled={loading || !q.trim()}
              className="h-[52px] px-5 bg-[#00F0FF] text-[#04090A] hover:bg-[#00F0FF]/90 disabled:opacity-50"
              data-testid="send-query-button"
            >
              <PaperPlaneRight size={16} weight="fill" />
            </Button>
          </form>
        </div>
      </main>

      {/* Right analysis + graph column */}
      <section className="w-full md:w-[420px] shrink-0 flex flex-col border-l border-[#00F0FF]/10">
        <div className="p-4 border-b border-[#00F0FF]/10">
          <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-2">retrieval pipeline</div>
          <RetrievalPipeline
            steps={current?.pipeline}
            active={loading ? activeStep : (current ? 6 : -1)}
          />
        </div>
        <div className="flex-1 min-h-0">
          <AnalysisPanel result={current} onExpandGraph={() => setGraphExpanded(true)} />
        </div>
      </section>

      {graphExpanded && (
        <div className="fixed inset-0 z-50 bg-[#020607]/95 p-4 md:p-8" role="dialog" aria-modal="true" aria-label="Expanded knowledge graph">
          <div className="h-full w-full border border-[#00F0FF]/20 bg-[#04090A] flex flex-col">
            <div className="shrink-0 px-4 py-3 border-b border-[#00F0FF]/15 flex items-center justify-between">
              <div>
                <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF]">interactive knowledge graph</div>
                <div className="text-xs text-[#8D9A9F] mt-1">
                  {current?.graph?.nodes?.length || 0} nodes · {current?.graph?.links?.length || 0} relationships · source: {current?.retrieved?.source || "Neo4j"}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setGraphExpanded(false)}
                className="p-2 text-[#8D9A9F] hover:text-[#00F0FF] transition-colors"
                aria-label="Close expanded graph"
                data-testid="close-expanded-knowledge-graph"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 min-h-0 relative">
              <KnowledgeGraph
                graph={current?.graph}
                highlighted={current?.retrieved?.highlighted_node_ids || []}
              />
              <div className="absolute bottom-4 left-4 z-10 max-w-xs border border-[#00F0FF]/15 bg-[#04090A]/90 p-3 text-[11px] font-mono-data text-[#8D9A9F]">
                <div className="text-[#E2F1F8] uppercase tracking-wider mb-2">legend</div>
                <div className="flex items-center gap-2 mb-1"><span className="w-2.5 h-2.5 rounded-full bg-[#00F0FF]" /> Cyan nodes: people in the retrieved communication paths</div>
                <div className="flex items-center gap-2 mb-1"><span className="w-2.5 h-2.5 rounded-full bg-[#FFB347]" /> Amber nodes: email records returned by Neo4j</div>
                <div className="text-[#56646A]">Glowing rings mark nodes directly highlighted by this query. Drag nodes, pan, and scroll to zoom.</div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function ResponseCard({ data }) {
  if (!data) return null;
  const redactions = data.moderation.redactions_applied || [];
  const preview = data.retrieved?.preview || [];
  return (
    <div className="border border-[#00F0FF]/15 bg-[#0B1215]/70 backdrop-blur-md p-5" data-testid="response-card">
      <details className="mb-4 border border-[#00F0FF]/15 bg-[#04090A]/50" data-testid="retrieval-preview">
        <summary className="cursor-pointer px-3 py-2 text-[11px] uppercase tracking-widest text-[#00F0FF]">
          Retrieved from {data.retrieved?.source || "Neo4j"} · {data.retrieved?.retrieval_mode || "unknown"} · {preview.length} disclosed record(s)
        </summary>
        <div className="px-3 pb-3 space-y-2 max-h-56 overflow-y-auto aegis-scrollbar">
          {preview.length === 0 ? (
            <div className="text-[12px] text-[#56646A]">
              {data.moderation?.disclosure_level === "HIGH"
                ? "Record-level details are withheld by the high-disclosure privacy policy."
                : "Neo4j returned no matching records."}
            </div>
          ) : preview.map((record, i) => (
            <div key={record.id || i} className="border-t border-[#00F0FF]/10 pt-2 text-[12px]">
              <div className="text-[#E2F1F8]">{record.subject || "(No subject)"}</div>
              <div className="font-mono-data text-[10px] text-[#8D9A9F]">
                {record.date || "undated"} · {record.sender || "unknown sender"}
              </div>
              {record.snippet && <div className="mt-1 text-[#E2F1F8]/70 line-clamp-2">{record.snippet}</div>}
            </div>
          ))}
        </div>
      </details>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <RiskBadge level={data.risk.level} score={data.risk.score} />
          <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#FFB347]/25 text-[#FFB347]">
            disclosure · {data.moderation.disclosure_level}
          </span>
          <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#00F0FF]/20 text-[#8D9A9F]">
            role · {data.risk.role_label}
          </span>
        </div>
        <div className="font-mono-data text-[10px] text-[#56646A]">
          confidence {Math.round((data.answer.confidence || 0) * 100)}% · {data.latency_ms}ms
        </div>
      </div>
      {data.moderation.disclosure_reason && (
        <p className="mb-3 text-[11px] leading-relaxed text-[#FFB347]">
          Disclosure is stricter than the behavioral risk score: {data.moderation.disclosure_reason}
        </p>
      )}
      <div className="prose prose-invert max-w-none text-[14px] leading-relaxed">
        <p className="text-[#E2F1F8]/95 whitespace-pre-wrap">{data.answer.summary}</p>
        {data.answer.findings?.length > 0 && (
          <>
            <div className="mt-3 mb-1 text-[11px] uppercase tracking-widest text-[#8D9A9F]">Key findings</div>
            <ul className="space-y-1.5 text-[#E2F1F8]/90">
              {data.answer.findings.map((f, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-[#00F0FF]">▸</span><span>{f}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {data.answer.sources?.length > 0 && (
          <>
            <div className="mt-4 mb-1 text-[11px] uppercase tracking-widest text-[#8D9A9F]">Retrieved sources</div>
            <div className="flex flex-wrap gap-1.5">
              {data.answer.sources.slice(0, 8).map((s, i) => (
                <span key={i} className="text-[11px] font-mono-data px-2 py-1 border border-[#00F0FF]/15 text-[#E2F1F8]/80">
                  {s}
                </span>
              ))}
            </div>
          </>
        )}
        {redactions.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {redactions.map((r) => (
              <span key={r} data-testid={`redaction-${r}`} className="text-[10px] font-mono-data uppercase tracking-widest px-2 py-0.5 border border-[#FFB347]/30 text-[#FFB347] bg-[#FFB347]/5">
                {data.moderation.disclosure_level === "HIGH" ? "withheld" : "redacted"} · {r}
              </span>
            ))}
          </div>
        )}
        <div className="mt-4 p-3 border border-[#FFB347]/25 bg-[#FFB347]/[0.04] text-[12px] text-[#E2F1F8]/85">
          <span className="text-[#FFB347] font-mono-data text-[10px] uppercase tracking-widest mr-2">moderation</span>
          {data.moderation.explanation}
        </div>
      </div>
    </div>
  );
}
