import { useEffect, useRef, useState } from "react";
import "@/App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const UI_URL = `${BACKEND_URL}/api/ui`;

function App() {
  const iframeRef = useRef(null);
  const [status, setStatus] = useState({ ok: null, version: null, error: null });

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/health`)
      .then((r) => r.json())
      .then((d) => setStatus({ ok: d.status === "ok", version: d.version, error: null }))
      .catch((e) => setStatus({ ok: false, version: null, error: String(e) }));
  }, []);

  return (
    <div
      data-testid="chanakya-app-shell"
      style={{
        margin: 0,
        padding: 0,
        height: "100vh",
        width: "100vw",
        display: "flex",
        flexDirection: "column",
        background: "#0a0a0a",
        color: "#e7e7e7",
        fontFamily: "DM Sans, system-ui, sans-serif",
      }}
    >
      <div
        data-testid="chanakya-topbar"
        style={{
          padding: "8px 16px",
          background: "#0f0f10",
          borderBottom: "1px solid #1f1f22",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 13,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <strong style={{ letterSpacing: 0.5 }}>Chanakya AI v5</strong>
          <span style={{ opacity: 0.6 }}>· Professional Trading Platform</span>
        </div>
        <div data-testid="chanakya-health-status" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: status.ok ? "#22c55e" : status.ok === false ? "#ef4444" : "#a3a3a3",
              boxShadow: status.ok ? "0 0 8px #22c55e" : "none",
            }}
          />
          <span style={{ opacity: 0.8 }}>
            {status.ok ? `backend ok · v${status.version}` : status.ok === false ? "backend down" : "checking…"}
          </span>
        </div>
      </div>
      <iframe
        ref={iframeRef}
        data-testid="chanakya-ui-iframe"
        title="Chanakya UI"
        src={UI_URL}
        style={{ border: "none", flex: 1, width: "100%", background: "#0a0a0a" }}
      />
    </div>
  );
}

export default App;
