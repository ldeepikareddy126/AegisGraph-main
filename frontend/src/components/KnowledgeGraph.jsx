import React, { useEffect, useMemo, useRef } from "react";
import ForceGraph2D from "react-force-graph-2d";

export default function KnowledgeGraph({ graph, highlighted = [], onExpand }) {
  const ref = useRef();
  const highlightSet = useMemo(() => new Set(highlighted || []), [highlighted]);
  const data = useMemo(() => {
    if (!graph) return { nodes: [], links: [] };
    return {
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.links.map((l) => ({ ...l })),
    };
  }, [graph]);

  useEffect(() => {
    if (ref.current && data.nodes.length) {
      setTimeout(() => ref.current && ref.current.zoomToFit(400, 40), 250);
    }
  }, [data]);

  if (!graph || !graph.nodes?.length) {
    return (
      <div className="h-full grid place-items-center text-[#56646A] text-xs font-mono-data">
        no graph details are available for this result
      </div>
    );
  }

  return (
    <div className="h-full w-full relative" data-testid="knowledge-graph">
      <div className="absolute top-2 right-3 z-10 flex items-center gap-3 text-[10px] font-mono-data text-[#8D9A9F] bg-[#04090A]/80 px-2 py-1 border border-[#00F0FF]/10">
        <span className="flex items-center gap-1.5"><i className="w-2 h-2 rounded-full bg-[#00F0FF] inline-block" /> Person</span>
        <span className="flex items-center gap-1.5"><i className="w-2 h-2 rounded-full bg-[#FFB347] inline-block" /> Email</span>
        <span className="text-[#56646A]">ring = retrieved</span>
      </div>
      {onExpand && (
        <button
          type="button"
          onClick={onExpand}
          className="absolute bottom-3 right-3 z-10 px-2.5 py-1.5 border border-[#00F0FF]/25 bg-[#04090A]/90 text-[10px] font-mono-data uppercase tracking-wider text-[#00F0FF] hover:border-[#00F0FF] transition-colors"
          data-testid="expand-knowledge-graph"
        >
          expand graph · {data.nodes.length} nodes
        </button>
      )}
      <ForceGraph2D
        ref={ref}
        graphData={data}
        backgroundColor="rgba(0,0,0,0)"
        width={undefined}
        nodeLabel={(n) => `${n.type}: ${n.label}`}
        linkColor={() => "rgba(0,240,255,0.15)"}
        linkWidth={0.7}
        cooldownTicks={80}
        d3AlphaDecay={0.03}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const isHi = highlightSet.has(node.id);
          const isEmail = node.type === "Email";
          const r = isEmail ? 3 : 4.5;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
          const fill = isHi
            ? isEmail ? "#FFB347" : "#00F0FF"
            : isEmail ? "rgba(255,179,71,0.35)" : "rgba(0,240,255,0.35)";
          ctx.fillStyle = fill;
          ctx.fill();
          if (isHi) {
            ctx.shadowBlur = 12; ctx.shadowColor = fill;
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 1.5, 0, 2 * Math.PI, false);
            ctx.strokeStyle = fill; ctx.lineWidth = 0.8; ctx.stroke();
            ctx.shadowBlur = 0;
          }
          if (globalScale > 1.6 && !isEmail) {
            ctx.fillStyle = "#E2F1F8";
            ctx.font = "500 4px Manrope, sans-serif";
            ctx.fillText(node.label || node.id, node.x + r + 2, node.y + 1.5);
          }
        }}
      />
    </div>
  );
}
