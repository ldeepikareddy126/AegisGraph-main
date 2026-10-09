import React from "react";
import { motion } from "framer-motion";

const styles = {
  LOW:    "risk-low",
  MEDIUM: "risk-med",
  HIGH:   "risk-high",
};

const dot = {
  LOW:    "bg-[#00E676] shadow-[0_0_10px_#00E676]",
  MEDIUM: "bg-[#FFB347] shadow-[0_0_10px_#FFB347]",
  HIGH:   "bg-[#FF3366] shadow-[0_0_10px_#FF3366]",
};

export default function RiskBadge({ level = "LOW", score }) {
  const cls = styles[level] || styles.LOW;
  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      data-testid={`risk-badge-${level.toLowerCase()}`}
      className={`inline-flex items-center gap-2 px-3 py-1 border font-mono-data text-xs uppercase tracking-widest ${cls}`}
    >
      <span className={`inline-block w-2 h-2 rounded-full pulse-dot ${dot[level]}`} />
      {level} risk
      {typeof score === "number" && (
        <span className="opacity-80 ml-1">{score.toFixed(2)}</span>
      )}
    </motion.span>
  );
}
