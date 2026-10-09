import React, { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import RiskBadge from "@/components/RiskBadge";
import RetrievalPipeline from "@/components/RetrievalPipeline";
import KnowledgeGraph from "@/components/KnowledgeGraph";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { motion } from "framer-motion";
import { CheckCircle, XCircle, ArrowsHorizontal } from "@phosphor-icons/react";
import { toast } from "sonner";

const ROLES = [
  { id: "external",  label: "External"  },
  { id: "employee",  label: "Employee"  },
  { id: "executive", label: "Executive" },
  { id: "legal",     label: "Legal"     },
  { id: "admin",     label: "Administrator" },
];

export default function CompareModal({ open, onOpenChange, scenario }) {
  const [roleA, setRoleA] = useState("external");
  const [roleB, setRoleB] = useState("legal");
  const [loading, setLoading] = useState(false);
  const [data, setData]     = useState(null);

  useEffect(() => {
    setData(null);
  }, [open, scenario?.id]);

  const disabled = useMemo(() => !scenario || loading || roleA === roleB, [scenario, loading, roleA, roleB]);

  const run = async () => {
    if (!scenario) return;
    setLoading(true); setData(null);
    try {
      const { data } = await api.post("/simulator/compare", {
        scenario_id: scenario.id,
        roles: [roleA, roleB],
      });
      if (data.scenario?.id !== scenario.id) {
        throw new Error("Comparison response did not match the selected scenario.");
      }
      setData(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Compare run failed");
    } finally { setLoading(false); }
  };

  const runs = data && scenario && data.scenario?.id === scenario.id
    ? data.runs || []
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl glass border-[#00F0FF]/20 text-[#E2F1F8] max-h-[90vh] overflow-y-auto aegis-scrollbar" data-testid="compare-modal">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <ArrowsHorizontal size={18} weight="duotone" className="text-[#00F0FF]" />
            <DialogTitle className="font-display text-lg">
              Compare roles · <span className="text-[#00F0FF]">{scenario?.title}</span>
            </DialogTitle>
          </div>
          <p className="text-[12px] text-[#8D9A9F]">
            Same prompt, same corpus, same LLM — only the caller's role changes.
            Runs are ephemeral and not written to history.
            Role bias changes the pre-gate score; hard safety gates and disclosure rules are role-independent.
          </p>
        </DialogHeader>

        <div className="flex flex-wrap items-end gap-3 py-3">
          <RoleSelect label="Role A" value={roleA} onChange={setRoleA} testid="compare-role-a" />
          <div className="text-[#00F0FF] font-mono-data text-lg">vs</div>
          <RoleSelect label="Role B" value={roleB} onChange={setRoleB} testid="compare-role-b" />
          <Button
            onClick={run}
            disabled={disabled}
            className="ml-auto bg-[#00F0FF] text-[#04090A] hover:bg-[#00F0FF]/90 disabled:opacity-50"
            data-testid="compare-run-btn"
          >
            {loading ? "Running…" : "Run comparison"}
          </Button>
        </div>

        {roleA === roleB && (
          <div className="text-[12px] text-[#FFB347]">Choose two different roles to compare.</div>
        )}

        {runs.length === 2 && (
          <div className="grid md:grid-cols-2 gap-4 mt-2">
            {runs.map((r, i) => (
              <CompareCol key={r.role} run={r} highlightSide={i === 0 ? "left" : "right"} />
            ))}
          </div>
        )}

        {runs.length === 2 && (
          <div className="mt-4 p-3 border border-[#00F0FF]/15 bg-[#0B1215]/60 text-[12px] leading-relaxed">
            <span className="font-mono-data text-[10px] uppercase tracking-widest text-[#00F0FF] mr-2">insight</span>
            {buildInsight(runs)}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function RoleSelect({ label, value, onChange, testid }) {
  return (
    <div>
      <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A] mb-1">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        className="bg-[#04090A] border border-[#00F0FF]/20 text-[#E2F1F8] px-3 py-2 text-[13px] font-mono-data focus:outline-none focus:border-[#00F0FF]"
      >
        {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
      </select>
    </div>
  );
}

function CompareCol({ run, highlightSide }) {
  const r = run.result;
  const badgeStyle = highlightSide === "left" ? "border-[#00F0FF]/30" : "border-[#FFB347]/30";
  return (
    <motion.div
      initial={{ opacity: 0, x: highlightSide === "left" ? -8 : 8 }}
      animate={{ opacity: 1, x: 0 }}
      className={`border ${badgeStyle} bg-[#0B1215]/60 p-4`}
      data-testid={`compare-col-${run.role}`}
    >
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono-data text-[10px] uppercase tracking-widest px-2 py-1 border border-[#00F0FF]/25 text-[#00F0FF]">
            role · {run.role}
          </span>
          <RiskBadge level={r.risk.level} score={r.risk.score} />
        </div>
        {run.evaluation?.passed ? (
          <CheckCircle size={16} weight="fill" className="text-[#00E676]" />
        ) : (
          <XCircle size={16} weight="fill" className="text-[#FF3366]" />
        )}
      </div>

      <div className="mb-3">
        <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A] mb-1">pipeline</div>
        <RetrievalPipeline steps={r.pipeline} active={6} />
      </div>
      <div className="mb-3 font-mono-data text-[10px] uppercase tracking-widest text-[#FFB347]">
        disclosure policy · {r.moderation.disclosure_level}
        {r.moderation.disclosure_reason && ` · ${r.moderation.disclosure_reason}`}
      </div>

      <section className="mb-3 border border-[#00F0FF]/15 bg-[#04090A]/70" data-testid={`compare-graph-${run.role}`}>
        <div className="px-3 py-2 border-b border-[#00F0FF]/10 font-mono-data text-[9px] uppercase tracking-widest text-[#8D9A9F]">
          disclosed graph · {r.graph?.nodes?.length || 0} nodes · {r.graph?.links?.length || 0} links
          {r.moderation.disclosure_level === "MEDIUM" && (
            <span className="ml-2 text-[#FFB347]">identities anonymized</span>
          )}
        </div>
        {r.moderation.disclosure_level === "HIGH" ? (
          <div className="h-36 grid place-items-center px-3 text-center text-[10px] text-[#8D9A9F]">
            Graph details are withheld by HIGH disclosure policy.
          </div>
        ) : r.graph?.nodes?.length > 0 ? (
          <div className="h-44 relative">
            <KnowledgeGraph
              graph={r.graph}
              highlighted={r.retrieved?.highlighted_node_ids || []}
            />
          </div>
        ) : (
          <div className="h-36 grid place-items-center px-3 text-center text-[10px] text-[#8D9A9F]">
            No connected nodes were returned for the disclosed matching records.
          </div>
        )}
      </section>

      <div className="font-mono-data text-[10px] uppercase tracking-widest text-[#56646A] mb-1">summary</div>
      <p className="text-[13px] text-[#E2F1F8]/90 whitespace-pre-wrap leading-relaxed">
        {r.answer.summary}
      </p>

      {r.moderation.redactions_applied?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {r.moderation.redactions_applied.map((x) => (
            <span key={x} className="text-[10px] font-mono-data uppercase tracking-widest px-2 py-0.5 border border-[#FFB347]/30 text-[#FFB347] bg-[#FFB347]/5">
              {r.moderation.disclosure_level === "HIGH" ? "withheld" : "redacted"} · {x}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-center font-mono-data text-[10px]">
        <Metric label="composite" value={r.risk.composite.toFixed(2)} />
        <Metric label="adjust"    value={(r.risk.role_adjustment >= 0 ? "+" : "") + r.risk.role_adjustment.toFixed(2)} />
        <Metric label="role-adjusted" value={Number(r.risk.role_adjusted ?? r.risk.score).toFixed(2)} />
        <Metric label="hard-gate floor" value={Number(r.risk.hard_gate || 0).toFixed(2)} />
        <Metric label="final score" value={Number(r.risk.score).toFixed(2)} />
        <Metric label="k_eff records" value={r.moderation.k_eff} />
      </div>
    </motion.div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="border border-[#00F0FF]/10 p-2">
      <div className="text-[9px] uppercase tracking-widest text-[#56646A]">{label}</div>
      <div className="text-[12px] text-[#E2F1F8] mt-0.5">{value}</div>
    </div>
  );
}

function buildInsight(runs) {
  const [a, b] = runs;
  const la = a.result.risk.level;
  const lb = b.result.risk.level;
  const sa = a.result.risk.score;
  const sb = b.result.risk.score;
  const preGateA = a.result.risk.role_adjusted ?? sa;
  const preGateB = b.result.risk.role_adjusted ?? sb;
  const preGateDelta = Math.abs(preGateA - preGateB).toFixed(2);
  const finalDelta = Math.abs(sa - sb).toFixed(2);
  const gateA = a.result.risk.hard_gate || 0;
  const gateB = b.result.risk.hard_gate || 0;
  const disclosureA = a.result.moderation.disclosure_level;
  const disclosureB = b.result.moderation.disclosure_level;
  const responseInsight = disclosureA === "HIGH" && disclosureB === "HIGH"
    ? "HIGH disclosure releases no records and standardizes the response."
    : disclosureA === disclosureB
      ? `Both use ${disclosureA} disclosure, so answers can match when evidence and generation align.`
      : `Disclosure differs (${disclosureA} vs ${disclosureB}), so the released evidence can differ.`;
  if (la === lb) {
    if (gateA > 0 || gateB > 0) {
      return (
        `Both roles received ${la} because a role-independent hard safety gate ` +
        `sets a minimum score of ${Math.max(gateA, gateB).toFixed(2)}. Their ` +
        `role-adjusted scores before that gate are ${preGateA.toFixed(2)} and ` +
        `${preGateB.toFixed(2)} (${preGateDelta} apart); the final gated scores ` +
        `are ${sa.toFixed(2)} and ${sb.toFixed(2)}. ${responseInsight}`
      );
    }
    if (finalDelta === "0.00") {
      if (preGateA === 1 && preGateB === 1) {
        return (
          `Both role-adjusted scores reached the 1.00 ceiling, so role bias ` +
          `cannot increase the final score further. ${responseInsight}`
        );
      }
      return (
        `Both roles produced the same role-adjusted score (${preGateA.toFixed(2)}); ` +
        `the configured role biases or score rounding leave no visible score spread. ` +
        `${responseInsight}`
      );
    }
    return (
      `Both roles remain ${la}, so the same disclosure tier and evidence are used. ` +
      `The role-adjusted scores are ${preGateA.toFixed(2)} and ${preGateB.toFixed(2)} ` +
      `(${preGateDelta} apart); the role bias changes monitoring risk, not the ` +
      `caller’s underlying graph permissions. Responses can therefore be the same ` +
      `when the roles remain in the same disclosure tier.`
    );
  }
  const higher = sa > sb ? a : b;
  const lower  = sa > sb ? b : a;
  return (
    `Role '${higher.role}' reached ${higher.result.risk.level} while '${lower.role}' landed at ` +
    `${lower.result.risk.level} — a ${finalDelta}-point spread in final risk ` +
    `(${preGateDelta} points before any hard gate). The changed risk tier can alter ` +
    `disclosure granularity; role does not bypass authorization or privacy policy.`
  );
}
