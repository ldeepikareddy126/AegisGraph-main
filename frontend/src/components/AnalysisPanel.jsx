import React from "react";
import RiskBadge from "./RiskBadge";
import KnowledgeGraph from "./KnowledgeGraph";
import { motion } from "framer-motion";

function Metric({ label, value, mono = true }) {
  return (
    <div className="flex items-baseline justify-between border-b border-[#00F0FF]/10 py-2">
      <span className="text-[11px] uppercase tracking-widest text-[#56646A]">{label}</span>
      <span className={`text-sm text-[#E2F1F8] ${mono ? "font-mono-data" : ""}`}>{value}</span>
    </div>
  );
}

export default function AnalysisPanel({ result, onExpandGraph }) {
  if (!result) {
    return (
      <div className="glass p-6 h-full flex items-center justify-center text-[#56646A] text-xs font-mono-data">
        analysis will appear here after a query
      </div>
    );
  }
  const r = result.risk;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="glass p-5 h-full overflow-y-auto aegis-scrollbar"
      data-testid="analysis-panel"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-display text-sm uppercase tracking-widest text-[#8D9A9F]">Analysis</h3>
        <RiskBadge level={r.level} score={r.score} />
      </div>

      <div className="mb-4">
        <div className="text-[11px] uppercase tracking-widest text-[#56646A] mb-1">Reasoning</div>
        <p className="text-[13px] text-[#E2F1F8]/90 leading-relaxed">{r.reasoning}.</p>
      </div>

      <Metric label="composite score" value={r.composite?.toFixed(3)} />
      <Metric label="EWMA smoothed"  value={r.raw_ewma?.toFixed(3)} />
      <Metric label="role monitoring bias" value={(r.role_adjustment >= 0 ? "+" : "") + r.role_adjustment.toFixed(2)} />
      <Metric label="role-adjusted score" value={Number(r.role_adjusted ?? r.score).toFixed(3)} />
      <Metric label="hard-gate floor" value={Number(r.hard_gate || 0).toFixed(3)} />
      <Metric label="final risk score" value={r.score?.toFixed(3)} />
      {r.hard_gate_reason && (
        <div className="mb-3 text-[11px] text-[#FFB347] leading-relaxed">
          Hard safety gate: {r.hard_gate_reason}
        </div>
      )}
      <Metric label="disclosure policy" value={result.moderation.disclosure_level} />
      {result.moderation.disclosure_reason && (
        <div className="mb-3 text-[11px] text-[#FFB347] leading-relaxed">
          {result.moderation.disclosure_reason}
        </div>
      )}
      <Metric label="k_eff (records)" value={result.moderation.k_eff} />
      <Metric label="released emails" value={result.retrieved.count} />
      <Metric label="graph nodes" value={result.graph?.nodes?.length || 0} />
      <Metric label="graph relationships" value={result.graph?.links?.length || 0} />
      <Metric label="source"         value={result.retrieved.source} />
      <Metric
        label="search mode"
        value={result.retrieved.retrieval_mode === "semantic"
          ? "semantic vector"
          : result.retrieved.retrieval_mode === "literal_fallback"
            ? "literal fallback · index pending"
            : result.retrieved.retrieval_mode || "unknown"}
      />
      {result.retrieved.retrieval_mode === "semantic" && (
        <Metric
          label="top relevance"
          value={result.retrieved.preview?.[0]?.relevance_score?.toFixed(3) ?? "—"}
        />
      )}
      <Metric label="latency"        value={`${result.latency_ms} ms`} />
      <Metric label="retrieval"      value={`${result.retrieval_ms} ms`} />

      <div className="mt-4 border border-[#00F0FF]/15 bg-[#04090A] rounded-sm overflow-hidden" data-testid="analysis-graph-preview">
        <div className="px-3 py-2 flex items-center justify-between border-b border-[#00F0FF]/10">
          <div className="text-[10px] uppercase tracking-[0.2em] text-[#56646A]">
            graph preview · {result.graph?.nodes?.length || 0} nodes
          </div>
          <span className="text-[10px] font-mono-data text-[#56646A]">
            {result.graph?.links?.length || 0} links
          </span>
        </div>
        <div className="h-40 relative">
          <KnowledgeGraph
            graph={result.graph}
            highlighted={result.retrieved?.highlighted_node_ids || []}
            onExpand={onExpandGraph}
          />
        </div>
      </div>

      <div className="mt-4">
        <div className="text-[11px] uppercase tracking-widest text-[#56646A] mb-1">Signals</div>
        {Object.entries(r.signals).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 py-1">
            <span className="w-16 text-[11px] font-mono-data text-[#8D9A9F]">{k}</span>
            <div className="flex-1 h-1 bg-[#00F0FF]/10 relative">
              <div
                className="h-full bg-[#00F0FF]"
                style={{ width: `${Math.min(100, Math.max(4, v * 100))}%` }}
              />
            </div>
            <span className="w-10 text-right font-mono-data text-[11px] text-[#E2F1F8]">
              {v.toFixed(2)}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-4">
        <div className="text-[11px] uppercase tracking-widest text-[#56646A] mb-1">Released subjects</div>
        <ul className="space-y-1">
          {result.retrieved.matched_subjects.slice(0, 6).map((s, i) => (
            <li key={i} className="text-[12px] text-[#E2F1F8]/80 truncate">• {s}</li>
          ))}
          {result.retrieved.matched_subjects.length === 0 && (
            <li className="text-[12px] text-[#56646A]">— none —</li>
          )}
        </ul>
      </div>

      <div className="mt-4 p-3 border border-[#FFB347]/30 bg-[#FFB347]/5">
        <div className="text-[11px] uppercase tracking-widest text-[#FFB347] mb-1">Moderation</div>
        <p className="text-[12px] text-[#E2F1F8]/85 leading-relaxed">
          {result.moderation.explanation}
        </p>
      </div>
    </motion.div>
  );
}
