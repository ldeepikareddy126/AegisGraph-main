import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, GoogleLogo } from "@phosphor-icons/react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID;

export default function Login() {
  const nav = useNavigate();
  const { setUser } = useAuth();
  const btnRef = useRef(null);

  useEffect(() => {
    if (!CLIENT_ID) {
      console.error("REACT_APP_GOOGLE_CLIENT_ID is not set");
      return;
    }
    // Load Google Identity Services once and render the official button.
    const render = () => {
      /* global google */
      if (!window.google?.accounts?.id || !btnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (resp) => {
          try {
            const { data } = await api.post("/auth/google", { credential: resp.credential });
            setUser(data);
            nav("/dashboard", { replace: true, state: { user: data } });
          } catch (e) {
            toast.error(e?.response?.data?.detail || "Sign-in failed");
          }
        },
      });
      window.google.accounts.id.renderButton(btnRef.current, {
        theme: "filled_black", size: "large", shape: "rectangular",
        text: "continue_with", logo_alignment: "center", width: 300,
      });
    };
    if (window.google?.accounts?.id) { render(); return; }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true; s.defer = true; s.onload = render;
    document.head.appendChild(s);
  }, [nav, setUser]);

  return (
    <div className="relative min-h-screen bg-[#04090A] overflow-hidden noise-overlay">
      <div className="absolute inset-0 grid-lines opacity-40" />
      <div
        className="absolute inset-0 opacity-30 bg-cover bg-center"
        style={{ backgroundImage: "url('https://images.unsplash.com/photo-1766997199917-dba5bfde06b2?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1Nzh8MHwxfHNlYXJjaHwyfHxkaWdpdGFsJTIwYWJzdHJhY3QlMjBtYXRyaXglMjBub2RlcyUyMGRlZXAlMjBncmVlbnxlbnwwfHx8fDE3ODQwMzkzOTN8MA&ixlib=rb-4.1.0&q=85')" }}
      />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#04090A]/60 to-[#04090A]" />

      <div className="relative z-10 min-h-screen flex flex-col md:flex-row">
        <div className="md:flex-1 p-10 md:p-16 flex flex-col justify-between">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="flex items-center gap-3">
            <div className="w-9 h-9 grid place-items-center border border-[#00F0FF]/40 shadow-[0_0_20px_rgba(0,240,255,0.15)]">
              <Shield size={20} weight="duotone" className="text-[#00F0FF]" />
            </div>
            <div>
              <div className="font-display text-lg tracking-tight text-[#E2F1F8]">AegisGraph</div>
              <div className="font-mono-data text-[10px] text-[#56646A] uppercase tracking-widest">privacy-aware KG-RAG</div>
            </div>
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.5 }}>
            <div className="font-mono-data text-[11px] text-[#00F0FF] mb-4 uppercase tracking-[0.3em]">research prototype · v0.1</div>
            <h1 className="font-display font-black text-5xl md:text-6xl leading-none tracking-tight text-[#E2F1F8]">
              Retrieval that <span className="text-[#00F0FF]">watches</span><br />itself.
            </h1>
            <p className="mt-6 max-w-md text-[#8D9A9F] leading-relaxed">
              AegisGraph combines a Neo4j knowledge graph over the Enron corpus with a behaviour-aware risk engine.
              Every response is moderated by an attention-fused privacy score before it reaches you.
            </p>
          </motion.div>

          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35 }} className="font-mono-data text-[11px] text-[#56646A]">
            enron mail corpus · neo4j semantic retrieval · adaptive privacy
          </motion.div>
        </div>

        <div className="md:w-[420px] p-10 md:p-16 flex items-center">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25, duration: 0.5 }} className="w-full glass p-8">
            <div className="font-mono-data text-[10px] uppercase tracking-[0.3em] text-[#00F0FF] mb-2">secure access</div>
            <h2 className="font-display text-2xl text-[#E2F1F8] mb-6">Sign in to continue</h2>

            {CLIENT_ID ? (
              <div ref={btnRef} data-testid="google-signin-btn" className="flex justify-center" />
            ) : (
              <div className="flex items-center gap-3 py-3 px-4 border border-red-500/40 text-red-300 text-sm">
                <GoogleLogo size={18} />
                Set <code className="font-mono-data">REACT_APP_GOOGLE_CLIENT_ID</code> in <code>frontend/.env</code>
              </div>
            )}

            <div className="mt-6 font-mono-data text-[10px] text-[#56646A] leading-relaxed">
              You&apos;ll sign in with Google. We only see your name, email, and avatar.
              Session token is stored as an httpOnly cookie for 7 days.
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
