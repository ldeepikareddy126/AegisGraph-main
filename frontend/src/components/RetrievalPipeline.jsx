import React from "react";
import { motion } from "framer-motion";
import { CheckCircle, CircleNotch, Circle } from "@phosphor-icons/react";

const DEFAULT_STEPS = [
  "Intent Detection",
  "Knowledge Graph Retrieval",
  "Privacy Risk Analysis",
  "Context Filtering",
  "AI Response Generation",
  "Final Moderated Response",
];

export default function RetrievalPipeline({ steps, active = -1 }) {
  const items = steps && steps.length ? steps : DEFAULT_STEPS.map((s) => ({ step: s, status: "pending" }));

  return (
    <ol className="space-y-3" data-testid="retrieval-pipeline">
      {items.map((it, i) => {
        const label = typeof it === "string" ? it : it.step;
        const status = typeof it === "string" ? "pending" : it.status;
        const detail = typeof it === "string" ? "" : it.detail;
        const isActive = i === active;
        const isDone = status === "done" || (active >= 0 && i < active);
        return (
          <motion.li
            key={label}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.06 }}
            className="flex items-start gap-3"
            data-testid={`pipeline-step-${i}`}
          >
            <span className="mt-0.5">
              {isDone ? (
                <CheckCircle size={18} weight="fill" className="text-[#00E676]" />
              ) : isActive ? (
                <CircleNotch size={18} weight="bold" className="text-[#00F0FF] animate-spin" />
              ) : (
                <Circle size={18} weight="bold" className="text-[#56646A]" />
              )}
            </span>
            <div className="flex-1">
              <div className={`text-[13px] ${isActive ? "text-[#00F0FF]" : isDone ? "text-[#E2F1F8]" : "text-[#8D9A9F]"}`}>
                {label}
              </div>
              {detail && (
                <div className="font-mono-data text-[11px] text-[#56646A] mt-0.5 whitespace-normal break-words line-clamp-2 leading-relaxed">
                  {detail}
                </div>
              )}
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}
