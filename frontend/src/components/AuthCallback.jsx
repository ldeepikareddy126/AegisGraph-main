import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";

// Legacy Emergent-Auth landing point. Google Identity Services returns the
// credential directly to the Login page callback, so we just clear the hash
// and bounce home if anything ever lands here.
export default function AuthCallback() {
  const nav = useNavigate();
  useEffect(() => {
    window.history.replaceState({}, "", "/");
    nav("/", { replace: true });
  }, [nav]);
  return null;
}
