import React, { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Shield, ChatCircleText, ChartLine, Graph, SignOut, Database, ShieldWarning, UsersThree } from "@phosphor-icons/react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const linkCls = ({ isActive }) =>
  `flex items-center gap-3 px-3 py-2 text-[13px] border-l-2 ${
    isActive
      ? "border-[#00F0FF] text-[#E2F1F8] bg-[#00F0FF]/5"
      : "border-transparent text-[#8D9A9F] hover:text-[#E2F1F8] hover:bg-white/[0.02]"
  }`;

export default function AppSidebar({
  backendAvailable,
  neo4jConnected,
  semanticReady,
}) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [simAccess, setSimAccess] = useState(false);
  useEffect(() => {
    api.get("/simulator/access").then(r => setSimAccess(!!r.data?.allowed)).catch(() => {});
  }, [user?.role]);
  const doLogout = async () => { await logout(); nav("/", { replace: true }); };

  return (
    <aside className="w-full md:w-64 shrink-0 border-r border-[#00F0FF]/10 bg-[#04090A] flex flex-col" data-testid="app-sidebar">
      <div className="p-5 border-b border-[#00F0FF]/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 grid place-items-center border border-[#00F0FF]/40">
            <Shield size={16} weight="duotone" className="text-[#00F0FF]" />
          </div>
          <div>
            <div className="font-display text-sm text-[#E2F1F8]">AegisGraph</div>
            <div className="font-mono-data text-[9px] text-[#56646A] uppercase tracking-widest">
              kg-rag · privacy layer
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 py-3">
        <NavLink to="/dashboard" data-testid="nav-playground" className={linkCls}>
          <ChatCircleText size={16} weight="duotone" /> Playground
        </NavLink>
        <NavLink to="/history" data-testid="nav-history" className={linkCls}>
          <Graph size={16} weight="duotone" /> Query History
        </NavLink>
        <NavLink to="/profile" data-testid="nav-profile" className={linkCls}>
          <ChartLine size={16} weight="duotone" /> Risk Trend
        </NavLink>
        {user?.role === "admin" && (
          <NavLink to="/admin" data-testid="nav-admin" className={linkCls}>
            <UsersThree size={16} weight="duotone" /> Admin Activity
          </NavLink>
        )}
        {simAccess && (
          <NavLink to="/simulator" data-testid="nav-simulator" className={linkCls}>
            <ShieldWarning size={16} weight="duotone" /> Attack Simulator
          </NavLink>
        )}
      </nav>

      <div className="p-4 border-t border-[#00F0FF]/10 space-y-3">
        <div
          data-testid="neo4j-status"
          className="w-full flex items-center gap-2 justify-between px-3 py-2 border border-[#00F0FF]/20 text-[12px]"
        >
          <span className="flex items-center gap-2 text-[#E2F1F8]">
            <Database size={14} weight="duotone" className="text-[#00F0FF]" /> Neo4j
          </span>
          <span className={`font-mono-data text-[10px] uppercase tracking-widest ${neo4jConnected ? "text-[#00E676]" : "text-[#00F0FF]"}`}>
            {backendAvailable === null
              ? "CHECKING"
              : backendAvailable === false
                ? "API OFFLINE"
                : neo4jConnected === null
                  ? "STATUS UNKNOWN"
                  : neo4jConnected
                    ? semanticReady === false ? "LIVE · KEYWORD" : "LIVE"
                    : "UNAVAILABLE"}
          </span>
        </div>

        {user && (
          <div className="flex items-center gap-3">
            {user.picture ? (
              <img src={user.picture} alt="" className="w-8 h-8 rounded-full" />
            ) : (
              <div className="w-8 h-8 rounded-full bg-[#00F0FF]/20 grid place-items-center text-[#00F0FF] text-xs">
                {(user.name || user.email || "?").slice(0, 1)}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="text-[12px] text-[#E2F1F8] truncate">{user.name}</div>
              <div className="font-mono-data text-[10px] text-[#56646A] truncate">{user.email}</div>
            </div>
            <button onClick={doLogout} data-testid="logout-btn" className="text-[#8D9A9F] hover:text-[#FF3366] transition-colors">
              <SignOut size={16} />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
