import { useState, useEffect, useRef } from "react";

const COLORS = {
  bg: "#0a0e1a",
  panel: "#0f1628",
  border: "#1e2d4a",
  accent: "#00d4ff",
  green: "#00ff9f",
  red: "#ff4060",
  yellow: "#ffd700",
  orange: "#ff8c00",
  purple: "#a855f7",
  text: "#c8d8f0",
  muted: "#4a6080",
};

const nodes = [
  { id: "api", label: "Angel One API", sub: "SmartAPI REST + WebSocket", x: 50, y: 50, color: COLORS.purple, icon: "🌐" },
  { id: "broker", label: "Global Broker", sub: "broker/global_broker.py", x: 50, y: 200, color: COLORS.accent, icon: "🔌" },
  { id: "ws", label: "WebSocket LTP", sub: "broker/websocket_mgr.py", x: 250, y: 200, color: COLORS.orange, icon: "⚡" },
  { id: "cache", label: "Cache Layer", sub: "data_stream/cache.py TTL=60s", x: 50, y: 350, color: COLORS.yellow, icon: "💾" },
  { id: "dm", label: "Data Manager", sub: "data_stream/data_manager.py", x: 250, y: 350, color: COLORS.yellow, icon: "📊" },
  { id: "ind", label: "Indicators", sub: "engine/indicators.py\nEMA/RSI/MACD/ATR/VWAP/ST", x: 50, y: 500, color: "#00ff9f", icon: "📈" },
  { id: "smc", label: "Smart Money", sub: "engine/smart_money.py\nOB/BOS/VP", x: 250, y: 500, color: "#00ff9f", icon: "🧠" },
  { id: "fake", label: "Fake Breakout", sub: "engine/fake_breakout.py\n9 trap detectors", x: 450, y: 500, color: COLORS.red, icon: "🚫" },
  { id: "mtf", label: "MTF Analyzer", sub: "engine/mtf_analyzer.py\n1m/3m/5m/15m", x: 650, y: 500, color: "#a855f7", icon: "🔍" },
  { id: "scanner", label: "Scanner", sub: "engine/scanner.py\n_analyze() + scan_all()", x: 350, y: 650, color: COLORS.accent, icon: "🔱" },
  { id: "auto", label: "Auto Trader", sub: "trading/auto_trader.py\nSignal qualify check", x: 350, y: 800, color: COLORS.green, icon: "🤖" },
  { id: "paper", label: "Paper Engine", sub: "trading/paper_engine.py\nTrade placement", x: 150, y: 950, color: COLORS.green, icon: "📝" },
  { id: "adaptive", label: "Adaptive Manager", sub: "trading/adaptive_manager.py\nSL/Target trail", x: 550, y: 950, color: COLORS.orange, icon: "⚙️" },
  { id: "capital", label: "Capital Manager", sub: "trading/capital_manager.py\nPosition sizing", x: 350, y: 950, color: COLORS.yellow, icon: "💰" },
  { id: "db", label: "SQLite DB", sub: "data/chanakya_v5.db\ntrades/capital tables", x: 350, y: 1100, color: COLORS.purple, icon: "🗄️" },
  { id: "dash", label: "Dashboard", sub: "main.py Flask API\nFrontend UI", x: 350, y: 1250, color: COLORS.accent, icon: "🖥️" },
];

const edges = [
  { from: "api", to: "broker", label: "REST candles/LTP" },
  { from: "api", to: "ws", label: "WebSocket LTP" },
  { from: "broker", to: "cache", label: "candles TTL=60s" },
  { from: "ws", to: "dm", label: "live LTP feed" },
  { from: "dm", to: "cache", label: "warm cache" },
  { from: "cache", to: "ind", label: "OHLCV candles" },
  { from: "cache", to: "smc", label: "OHLCV candles" },
  { from: "cache", to: "fake", label: "OHLCV candles" },
  { from: "cache", to: "mtf", label: "4 timeframes" },
  { from: "ind", to: "scanner", label: "EMA/RSI/MACD/ATR score" },
  { from: "smc", to: "scanner", label: "OB/BOS/VP score" },
  { from: "fake", to: "scanner", label: "penalty/traps" },
  { from: "mtf", to: "scanner", label: "TF alignment boost" },
  { from: "scanner", to: "auto", label: "qualified signals" },
  { from: "auto", to: "paper", label: "place trade" },
  { from: "auto", to: "capital", label: "position size check" },
  { from: "capital", to: "paper", label: "qty/lots" },
  { from: "paper", to: "adaptive", label: "open trade" },
  { from: "adaptive", to: "db", label: "SL/Target update" },
  { from: "paper", to: "db", label: "trade record" },
  { from: "capital", to: "db", label: "capital update" },
  { from: "db", to: "dash", label: "P&L/trades/capital" },
];

// ─── Indicator Calculator ─────────────────────────────────────────────────────
function calcEMA(data, period) {
  if (data.length < period) return data[data.length - 1] || 0;
  const k = 2 / (period + 1);
  let e = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < data.length; i++) e = data[i] * k + e * (1 - k);
  return e;
}

function calcWilderRSI(closes, period = 14) {
  if (closes.length < period + 1) return 50;
  const gains = [], losses = [];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0));
    losses.push(Math.max(-d, 0));
  }
  let ag = gains.slice(0, period).reduce((a, b) => a + b) / period;
  let al = losses.slice(0, period).reduce((a, b) => a + b) / period;
  for (let i = period; i < gains.length; i++) {
    ag = (ag * (period - 1) + gains[i]) / period;
    al = (al * (period - 1) + losses[i]) / period;
  }
  if (al === 0) return 100;
  return 100 - 100 / (1 + ag / al);
}

function calcATR(candles, period = 14) {
  const trs = [];
  for (let i = 1; i < candles.length; i++) {
    const h = candles[i][0], l = candles[i][1], pc = candles[i - 1][2];
    trs.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  if (!trs.length) return 0;
  let atr = trs.slice(0, period).reduce((a, b) => a + b) / Math.min(period, trs.length);
  for (let i = period; i < trs.length; i++) atr = (atr * (period - 1) + trs[i]) / period;
  return atr;
}

function calcScore(params) {
  const { e9, e21, rsi, macdHist, ltp, vwap, volRatio, st, e200, at, direction } = params;
  let score = 0;
  const steps = [];

  if (direction === "BUY") {
    if (e9 > e21) { score += 25; steps.push({ label: "EMA9 > EMA21", pts: 25, ok: true }); }
    else steps.push({ label: "EMA9 < EMA21", pts: 0, ok: false });
    if (rsi > 40 && rsi < 70) { score += 20; steps.push({ label: `RSI ${rsi.toFixed(1)} in 40-70`, pts: 20, ok: true }); }
    else steps.push({ label: `RSI ${rsi.toFixed(1)} outside 40-70`, pts: 0, ok: false });
    if (macdHist > 0) { score += 15; steps.push({ label: "MACD hist > 0", pts: 15, ok: true }); }
    else steps.push({ label: "MACD hist ≤ 0", pts: 0, ok: false });
    if (vwap && ltp > vwap) { score += 20; steps.push({ label: `LTP ${ltp} > VWAP ${vwap.toFixed(2)}`, pts: 20, ok: true }); }
    else steps.push({ label: `LTP below VWAP`, pts: 0, ok: false });
    if (volRatio >= 1.2) { score += 10; steps.push({ label: `Vol ratio ${volRatio.toFixed(2)} ≥ 1.2`, pts: 10, ok: true }); }
    else steps.push({ label: `Vol ratio ${volRatio.toFixed(2)} < 1.2`, pts: 0, ok: false });
    if (st === "UP") { score += 10; steps.push({ label: "Supertrend UP", pts: 10, ok: true }); }
    else steps.push({ label: "Supertrend DOWN", pts: 0, ok: false });
  } else {
    if (e9 < e21) { score += 25; steps.push({ label: "EMA9 < EMA21", pts: 25, ok: true }); }
    else steps.push({ label: "EMA9 > EMA21", pts: 0, ok: false });
    if (rsi > 30 && rsi < 60) { score += 20; steps.push({ label: `RSI ${rsi.toFixed(1)} in 30-60`, pts: 20, ok: true }); }
    else steps.push({ label: `RSI ${rsi.toFixed(1)} outside 30-60`, pts: 0, ok: false });
    if (macdHist < 0) { score += 15; steps.push({ label: "MACD hist < 0", pts: 15, ok: true }); }
    else steps.push({ label: "MACD hist ≥ 0", pts: 0, ok: false });
    if (vwap && ltp < vwap) { score += 20; steps.push({ label: `LTP ${ltp} < VWAP ${vwap.toFixed(2)}`, pts: 20, ok: true }); }
    else steps.push({ label: `LTP above VWAP`, pts: 0, ok: false });
    if (volRatio >= 1.2) { score += 10; steps.push({ label: `Vol ratio ${volRatio.toFixed(2)} ≥ 1.2`, pts: 10, ok: true }); }
    else steps.push({ label: `Vol ratio ${volRatio.toFixed(2)} < 1.2`, pts: 0, ok: false });
    if (st === "DOWN") { score += 10; steps.push({ label: "Supertrend DOWN", pts: 10, ok: true }); }
    else steps.push({ label: "Supertrend UP", pts: 0, ok: false });
  }

  const withTrend = direction === "BUY" ? ltp > e200 : ltp < e200;
  const ema200Label = withTrend ? "WITH EMA200 trend (+15)" : "COUNTER EMA200 (-20)";
  const ema200Pts = withTrend ? 15 : -20;
  score = Math.min(100, Math.max(0, score + ema200Pts));
  steps.push({ label: ema200Label, pts: ema200Pts, ok: withTrend });

  const sl = direction === "BUY" ? ltp - 1.5 * at : ltp + 1.5 * at;
  const target = direction === "BUY" ? ltp + 3 * at : ltp - 3 * at;
  const rr = Math.abs(target - ltp) / Math.max(Math.abs(ltp - sl), 0.01);

  return { score, steps, sl, target, rr, withTrend };
}

// ─── Components ──────────────────────────────────────────────────────────────
function FlowNode({ node, active, onClick }) {
  return (
    <div
      onClick={() => onClick(node)}
      style={{
        position: "absolute",
        left: node.x,
        top: node.y,
        width: 160,
        background: active ? node.color + "22" : COLORS.panel,
        border: `1.5px solid ${active ? node.color : COLORS.border}`,
        borderRadius: 10,
        padding: "8px 12px",
        cursor: "pointer",
        boxShadow: active ? `0 0 16px ${node.color}55` : "none",
        transition: "all 0.2s",
        zIndex: 2,
      }}
    >
      <div style={{ fontSize: 18 }}>{node.icon}</div>
      <div style={{ color: node.color, fontWeight: 700, fontSize: 12, marginTop: 2 }}>{node.label}</div>
      <div style={{ color: COLORS.muted, fontSize: 9, marginTop: 2, lineHeight: 1.4 }}>{node.sub}</div>
    </div>
  );
}

function ScoreBar({ score }) {
  const color = score >= 75 ? COLORS.green : score >= 50 ? COLORS.yellow : COLORS.red;
  return (
    <div style={{ margin: "8px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ color: COLORS.muted, fontSize: 11 }}>Signal Score</span>
        <span style={{ color, fontWeight: 700, fontSize: 14 }}>{score}/100</span>
      </div>
      <div style={{ background: COLORS.border, borderRadius: 4, height: 8 }}>
        <div style={{ width: `${score}%`, background: color, borderRadius: 4, height: "100%", transition: "width 0.5s" }} />
      </div>
      <div style={{ color: COLORS.muted, fontSize: 10, marginTop: 4 }}>
        {score >= 75 ? "✅ Qualifies (≥75 INDEX)" : score >= 50 ? "⚠️ MCX only (≥50)" : "❌ Rejected (<50)"}
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("flow");
  const [activeNode, setActiveNode] = useState(null);
  const [form, setForm] = useState({
    symbol: "NIFTY", exchange: "NSE", direction: "BUY",
    ltp: 24000, high: 24050, low: 23950, prevClose: 23980,
    e9: 24010, e21: 23990, e200: 23800,
    rsi: 55, macdHist: 2.5, vwap: 23985, volRatio: 1.3, st: "UP",
    capital: 1000000, role: "developer",
  });
  const [result, setResult] = useState(null);

  const LOT_SIZES = { NIFTY: 65, BANKNIFTY: 30, FINNIFTY: 60, NATURALGAS: 1250, CRUDEOIL: 100, GOLDM: 100 };
  const MARGINS = { NIFTY: 75000, BANKNIFTY: 100000, FINNIFTY: 50000, NATURALGAS: 20000, CRUDEOIL: 50000, GOLDM: 60000 };
  const RISK_PCT = 2;

  function calculate() {
    const at = Math.max(form.high - form.low, 5) * 0.8;
    const res = calcScore({ ...form, at });
    const lotSize = LOT_SIZES[form.symbol] || 1;
    const margin = MARGINS[form.symbol] || 50000;
    const riskAmt = form.capital * RISK_PCT / 100;
    const pointRisk = Math.max(1.5 * at, form.ltp * 0.002);
    const rawQty = riskAmt / pointRisk;
    const lots = Math.floor(rawQty / lotSize);
    const qty = lots * lotSize;
    const marginNeeded = lots * margin;
    const capitalPct = (marginNeeded / form.capital * 100).toFixed(1);
    const winPnL = Math.round((form.direction === "BUY" ? res.target - form.ltp : form.ltp - res.target) * qty);
    const lossPnL = Math.round((form.direction === "BUY" ? res.sl - form.ltp : form.ltp - res.sl) * qty);
    setResult({ ...res, at, lotSize, margin, riskAmt, pointRisk, lots, qty, marginNeeded, capitalPct, winPnL, lossPnL });
  }

  const nodeInfo = {
    api: { desc: "Angel One SmartAPI provides REST candles and WebSocket live LTP.", output: "OHLCV candles, Live LTP" },
    broker: { desc: "global_broker.py manages broker connection, auth token, get_candles() and get_ltp() calls with retry logic.", output: "Candles array, LTP float" },
    ws: { desc: "websocket_mgr.py maintains SmartWebSocketV2 connection. Sends LTP updates every tick to cache. Auto-reconnects on disconnect.", output: "LTP dict {token: price}" },
    cache: { desc: "In-memory cache with TTL=60s. Key: candles_{symbol}_5m. Prevents repeated API calls.", output: "Cached candles list" },
    dm: { desc: "DataManager warms cache at startup for all watchlist symbols. Refreshes every 5 min.", output: "Warmed candle cache" },
    ind: { desc: "indicators.py: Wilder RSI, True ATR, Incremental MACD, Session VWAP, Proper Supertrend, EMA, Fibonacci, Pivot", output: "Score components (RSI, ATR, MACD, VWAP, ST)" },
    smc: { desc: "smart_money.py: Order Block detection, Break of Structure, Volume Profile POC/VAH/VAL. Blended 50% with classic score.", output: "SMC score 0-100, OB levels" },
    fake: { desc: "fake_breakout.py: 9 trap detectors (BullTrap, BearTrap, UpperWick, SellExhaustion etc). Applies penalty to signal score.", output: "penalty pts, traps list, is_fake bool" },
    mtf: { desc: "mtf_analyzer.py: Checks 1m/3m/5m/15m alignment. 4/4=+25, 3/4=+15, 2/4=-5, 0-1/4=-10", output: "aligned bool, score boost" },
    scanner: { desc: "_analyze(): Classic 50% + SMC 50% blend. EMA200 filter ±15/20. Fibonacci zone +20. scan_all() filters RR≥1.8, score≥50/75.", output: "Signal dict {symbol, direction, score, sl, target, rr}" },
    auto: { desc: "auto_trader.py: Qualify check (score≥75 INDEX, ≥50 MCX), soft/hard daily limit, max trades check, user loop.", output: "Trade instruction" },
    paper: { desc: "paper_engine.py: Creates trade record in DB. Calculates P&L on close. Updates capital.", output: "Trade ID, status OPEN/CLOSED" },
    capital: { desc: "capital_manager.py: Position sizing = risk_amt / point_risk. min_point_risk=0.2%. Floor to lot size.", output: "qty, lots, margin_est" },
    adaptive: { desc: "adaptive_manager.py: Every 5s checks SL hit, target hit. Trails SL at 1R→BE, 2R→+1R. Per-symbol target (NIFTY=5×, BANKNIFTY=3×). Momentum exit.", output: "Updated SL/Target, trade close" },
    db: { desc: "chanakya_v5.db: trades, paper_capital, user_trading_state, historical_candles tables.", output: "Persistent trade & capital records" },
    dash: { desc: "Flask API + Frontend. Serves /api/trades, /api/pnl, /api/capital, /api/signals endpoints.", output: "JSON API + UI display" },
  };

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", fontFamily: "'JetBrains Mono', monospace", color: COLORS.text, padding: 20 }}>
      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 24 }}>
        <div style={{ fontSize: 28, fontWeight: 900, color: COLORS.accent, letterSpacing: 2 }}>🔱 CHANAKYA AI v5</div>
        <div style={{ color: COLORS.muted, fontSize: 12, marginTop: 4 }}>Data Flow + Signal Calculator</div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, justifyContent: "center" }}>
        {["flow", "calculator", "pipeline"].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? COLORS.accent : COLORS.panel,
            color: tab === t ? "#000" : COLORS.muted,
            border: `1px solid ${tab === t ? COLORS.accent : COLORS.border}`,
            borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontWeight: 700,
            fontSize: 12, textTransform: "uppercase", letterSpacing: 1,
          }}>
            {t === "flow" ? "🗺 Data Flow" : t === "calculator" ? "🧮 Signal Calc" : "⚙️ Pipeline"}
          </button>
        ))}
      </div>

      {/* ── DATA FLOW TAB ── */}
      {tab === "flow" && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 300, position: "relative", height: 1320, background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, overflow: "hidden" }}>
            {/* Edges */}
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 1 }}>
              {edges.map((e, i) => {
                const from = nodes.find(n => n.id === e.from);
                const to = nodes.find(n => n.id === e.to);
                if (!from || !to) return null;
                const x1 = from.x + 80, y1 = from.y + 50;
                const x2 = to.x + 80, y2 = to.y + 10;
                return (
                  <g key={i}>
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={COLORS.border} strokeWidth={1.5} strokeDasharray="4 3" />
                    <text x={(x1 + x2) / 2 + 4} y={(y1 + y2) / 2} fill={COLORS.muted} fontSize={8} textAnchor="middle">{e.label}</text>
                  </g>
                );
              })}
            </svg>
            {nodes.map(n => (
              <FlowNode key={n.id} node={n} active={activeNode?.id === n.id} onClick={setActiveNode} />
            ))}
          </div>

          {/* Node Info Panel */}
          <div style={{ width: 280, background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20 }}>
            {activeNode ? (
              <>
                <div style={{ fontSize: 32, marginBottom: 8 }}>{activeNode.icon}</div>
                <div style={{ color: activeNode.color, fontWeight: 700, fontSize: 16 }}>{activeNode.label}</div>
                <div style={{ color: COLORS.muted, fontSize: 10, marginBottom: 12 }}>{activeNode.sub}</div>
                <div style={{ borderTop: `1px solid ${COLORS.border}`, paddingTop: 12 }}>
                  <div style={{ color: COLORS.text, fontSize: 12, lineHeight: 1.6 }}>{nodeInfo[activeNode.id]?.desc}</div>
                  <div style={{ marginTop: 12, background: COLORS.bg, borderRadius: 6, padding: "8px 10px" }}>
                    <div style={{ color: COLORS.muted, fontSize: 10, marginBottom: 4 }}>OUTPUT →</div>
                    <div style={{ color: COLORS.green, fontSize: 11 }}>{nodeInfo[activeNode.id]?.output}</div>
                  </div>
                </div>
              </>
            ) : (
              <div style={{ color: COLORS.muted, fontSize: 12, marginTop: 40, textAlign: "center" }}>
                👆 Click any node to see<br />data flow details
              </div>
            )}

            {/* Legend */}
            <div style={{ marginTop: 24, borderTop: `1px solid ${COLORS.border}`, paddingTop: 16 }}>
              <div style={{ color: COLORS.muted, fontSize: 10, marginBottom: 8 }}>LEGEND</div>
              {[
                { color: COLORS.purple, label: "External API" },
                { color: COLORS.accent, label: "Core Engine" },
                { color: COLORS.yellow, label: "Cache/Data" },
                { color: COLORS.green, label: "Trading Logic" },
                { color: COLORS.red, label: "Filter/Guard" },
                { color: COLORS.orange, label: "Management" },
              ].map(l => (
                <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: l.color }} />
                  <span style={{ fontSize: 11 }}>{l.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── CALCULATOR TAB ── */}
      {tab === "calculator" && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {/* Inputs */}
          <div style={{ flex: 1, minWidth: 300, background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20 }}>
            <div style={{ color: COLORS.accent, fontWeight: 700, marginBottom: 16, fontSize: 14 }}>📥 INPUT PARAMETERS</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {[
                { key: "symbol", label: "Symbol", type: "select", opts: ["NIFTY", "BANKNIFTY", "FINNIFTY", "NATURALGAS", "GOLDM", "CRUDEOIL"] },
                { key: "exchange", label: "Exchange", type: "select", opts: ["NSE", "MCX"] },
                { key: "direction", label: "Direction", type: "select", opts: ["BUY", "SELL"] },
                { key: "st", label: "Supertrend", type: "select", opts: ["UP", "DOWN"] },
                { key: "ltp", label: "LTP", type: "number" },
                { key: "high", label: "High", type: "number" },
                { key: "low", label: "Low", type: "number" },
                { key: "prevClose", label: "Prev Close", type: "number" },
                { key: "e9", label: "EMA9", type: "number" },
                { key: "e21", label: "EMA21", type: "number" },
                { key: "e200", label: "EMA200", type: "number" },
                { key: "rsi", label: "RSI (Wilder)", type: "number" },
                { key: "macdHist", label: "MACD Hist", type: "number" },
                { key: "vwap", label: "VWAP", type: "number" },
                { key: "volRatio", label: "Vol Ratio", type: "number" },
                { key: "capital", label: "Capital (Rs)", type: "number" },
              ].map(inp => (
                <div key={inp.key}>
                  <label style={{ color: COLORS.muted, fontSize: 10, display: "block", marginBottom: 3 }}>{inp.label}</label>
                  {inp.type === "select" ? (
                    <select value={form[inp.key]} onChange={e => f(inp.key, e.target.value)}
                      style={{ width: "100%", background: COLORS.bg, color: COLORS.text, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: "4px 6px", fontSize: 12 }}>
                      {inp.opts.map(o => <option key={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type="number" value={form[inp.key]} onChange={e => f(inp.key, parseFloat(e.target.value) || 0)}
                      style={{ width: "100%", background: COLORS.bg, color: COLORS.text, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: "4px 6px", fontSize: 12, boxSizing: "border-box" }} />
                  )}
                </div>
              ))}
            </div>
            <button onClick={calculate} style={{
              width: "100%", marginTop: 16, background: COLORS.accent, color: "#000",
              border: "none", borderRadius: 8, padding: "10px 0", fontWeight: 700,
              fontSize: 14, cursor: "pointer", letterSpacing: 1,
            }}>🔱 CALCULATE SIGNAL</button>
          </div>

          {/* Results */}
          <div style={{ flex: 1, minWidth: 300 }}>
            {result ? (
              <>
                {/* Score Breakdown */}
                <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20, marginBottom: 12 }}>
                  <div style={{ color: COLORS.accent, fontWeight: 700, marginBottom: 12, fontSize: 14 }}>📊 SCORE BREAKDOWN</div>
                  <ScoreBar score={result.score} />
                  <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                        <th style={{ color: COLORS.muted, fontSize: 10, textAlign: "left", padding: "4px 0" }}>CONDITION</th>
                        <th style={{ color: COLORS.muted, fontSize: 10, textAlign: "right", padding: "4px 0" }}>PTS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.steps.map((s, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${COLORS.border}22` }}>
                          <td style={{ padding: "5px 0", fontSize: 11, color: s.ok ? COLORS.text : COLORS.muted }}>
                            <span style={{ marginRight: 6 }}>{s.ok ? "✅" : "❌"}</span>{s.label}
                          </td>
                          <td style={{ textAlign: "right", fontSize: 11, color: s.pts > 0 ? COLORS.green : s.pts < 0 ? COLORS.red : COLORS.muted, fontWeight: 700 }}>
                            {s.pts > 0 ? `+${s.pts}` : s.pts}
                          </td>
                        </tr>
                      ))}
                      <tr style={{ borderTop: `2px solid ${COLORS.border}` }}>
                        <td style={{ padding: "6px 0", fontWeight: 700, color: COLORS.accent }}>FINAL SCORE</td>
                        <td style={{ textAlign: "right", fontWeight: 900, fontSize: 16, color: result.score >= 75 ? COLORS.green : result.score >= 50 ? COLORS.yellow : COLORS.red }}>{result.score}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* SL / Target */}
                <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20, marginBottom: 12 }}>
                  <div style={{ color: COLORS.accent, fontWeight: 700, marginBottom: 12, fontSize: 14 }}>🎯 SL / TARGET (ATR-based)</div>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <tbody>
                      {[
                        { label: "True ATR (14)", val: result.at.toFixed(2), color: COLORS.text },
                        { label: "Entry (LTP)", val: form.ltp, color: COLORS.text },
                        { label: "Stop Loss (1.5×ATR)", val: result.sl.toFixed(2), color: COLORS.red },
                        { label: "Target 3×ATR", val: result.target.toFixed(2), color: COLORS.green },
                        { label: "Extended 5×ATR", val: (form.direction === "BUY" ? form.ltp + 5 * result.at : form.ltp - 5 * result.at).toFixed(2), color: COLORS.accent },
                        { label: "Risk:Reward", val: `1:${result.rr.toFixed(2)}`, color: result.rr >= 1.8 ? COLORS.green : COLORS.red },
                      ].map(r => (
                        <tr key={r.label} style={{ borderBottom: `1px solid ${COLORS.border}22` }}>
                          <td style={{ color: COLORS.muted, fontSize: 11, padding: "5px 0" }}>{r.label}</td>
                          <td style={{ textAlign: "right", color: r.color, fontWeight: 700, fontSize: 12 }}>{r.val}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Position Sizing */}
                <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20 }}>
                  <div style={{ color: COLORS.accent, fontWeight: 700, marginBottom: 12, fontSize: 14 }}>💰 POSITION SIZING</div>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <tbody>
                      {[
                        { label: "Capital", val: `₹${form.capital.toLocaleString()}` },
                        { label: "Risk 2%", val: `₹${result.riskAmt.toLocaleString()}` },
                        { label: "Point Risk (min 0.2%)", val: result.pointRisk.toFixed(2) },
                        { label: "Lot Size", val: result.lotSize },
                        { label: "Lots", val: result.lots },
                        { label: "Total Qty", val: result.qty.toLocaleString() },
                        { label: "Margin Needed", val: `₹${result.marginNeeded.toLocaleString()}` },
                        { label: "Capital Used %", val: `${result.capitalPct}%`, color: parseFloat(result.capitalPct) > 70 ? COLORS.red : COLORS.green },
                        { label: "Win P&L (3×ATR)", val: `₹${result.winPnL.toLocaleString()}`, color: COLORS.green },
                        { label: "Loss P&L (SL hit)", val: `₹${result.lossPnL.toLocaleString()}`, color: COLORS.red },
                      ].map(r => (
                        <tr key={r.label} style={{ borderBottom: `1px solid ${COLORS.border}22` }}>
                          <td style={{ color: COLORS.muted, fontSize: 11, padding: "5px 0" }}>{r.label}</td>
                          <td style={{ textAlign: "right", color: r.color || COLORS.text, fontWeight: 700, fontSize: 12 }}>{r.val}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 40, textAlign: "center" }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>🧮</div>
                <div style={{ color: COLORS.muted, fontSize: 13 }}>Enter parameters and<br />click Calculate</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── PIPELINE TAB ── */}
      {tab === "pipeline" && (
        <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 12, padding: 20 }}>
          <div style={{ color: COLORS.accent, fontWeight: 700, marginBottom: 20, fontSize: 14 }}>⚙️ COMPLETE SIGNAL PIPELINE</div>
          {[
            {
              step: "1", title: "API → Candles", color: COLORS.purple,
              input: "Angel One SmartAPI call",
              process: "broker.get_candles(token, exchange, 'FIVE_MINUTE', days=2)",
              output: "225 candles [{ts, open, high, low, close, volume}]",
              check: "len(candles) >= 10",
            },
            {
              step: "2", title: "Cache Check", color: COLORS.yellow,
              input: "225 candles",
              process: "cget('candles_NIFTY_5m') → TTL=60s",
              output: "Cached or fresh candles",
              check: "TTL not expired",
            },
            {
              step: "3", title: "Indicators", color: COLORS.green,
              input: "OHLCV candles array",
              process: "EMA(9,21,200), Wilder RSI(14), MACD(12,26,9), True ATR(14), Session VWAP, Supertrend(10,3)",
              output: "e9, e21, e200, rsi, macd_hist, at, vwap, st",
              check: "Mathematical accuracy verified",
            },
            {
              step: "4", title: "Score (50% classic)", color: COLORS.accent,
              input: "Indicator values",
              process: "EMA cross +25, RSI range +20, MACD hist +15, VWAP bias +20, Volume +10, Supertrend +10 = max 100",
              output: "classic_score 0-100",
              check: "Direction = BUY if e9>e21 else SELL",
            },
            {
              step: "5", title: "SMC Score (50%)", color: COLORS.purple,
              input: "Candles + direction",
              process: "Order Block detection + BOS + Volume Profile → smc_score",
              output: "smc_score 0-100",
              check: "smc >= 20 (MCX) or 30 (NSE)",
            },
            {
              step: "6", title: "Blend + EMA200", color: COLORS.accent,
              input: "classic_score + smc_score",
              process: "final = 0.5×classic + 0.5×smc → EMA200 WITH +15, COUNTER -20",
              output: "blended_score 0-100",
              check: "EMA200 WITH-TREND preferred",
            },
            {
              step: "7", title: "Fibonacci Zone", color: COLORS.yellow,
              input: "LTP + 100-candle high/low",
              process: "Fib levels (23.6, 38.2, 50, 61.8, 78.6%) → zone check tol=0.3%",
              output: "+20 bonus if at key level",
              check: "BUY: 38.2/50/61.8, SELL: 23.6/38.2/78.6",
            },
            {
              step: "8", title: "SL / Target", color: COLORS.red,
              input: "LTP + ATR",
              process: "SL = LTP ± 1.5×ATR, Target = LTP ± 3×ATR, RR = target_dist/sl_dist",
              output: "sl, target, rr",
              check: "RR >= 1.8 required",
            },
            {
              step: "9", title: "Fake Breakout", color: COLORS.red,
              input: "Candles + signal",
              process: "9 detectors: BullTrap(-25), BearTrap(-25), UpperWick(-15), SellExh(-15), DojiIndecision(-10)...",
              output: "penalty deducted, traps list",
              check: "Serious fakes block score≥80 signals",
            },
            {
              step: "10", title: "MTF Alignment", color: COLORS.purple,
              input: "4 timeframes (1m/3m/5m/15m)",
              process: "4/4=+25, 3/4=+15, 2/4=-5, 0-1/4=-10",
              output: "Final adjusted score",
              check: "STRONG=4/4≥70, MODERATE=3/4≥55",
            },
            {
              step: "11", title: "Auto Trader Qualify", color: COLORS.green,
              input: "Final signal",
              process: "NSE INDEX: score≥75 | MCX: score≥50 | Daily loss check | Max trades check",
              output: "qualified=True/False",
              check: "Hard limit 7.5%, Soft limit 5%+signal_score",
            },
            {
              step: "12", title: "Position Sizing", color: COLORS.yellow,
              input: "Capital + entry + sl",
              process: "risk=2%×capital / max(point_risk, 0.2%×ltp) → floor to lot_size",
              output: "qty, lots, margin_est",
              check: "min_risk prevents huge lots",
            },
            {
              step: "13", title: "Trade Placed", color: COLORS.green,
              input: "qty, entry, sl, target",
              process: "paper_engine.place_trade() → DB insert → adaptive_manager monitors every 5s",
              output: "Trade ID, status=OPEN",
              check: "SL trail: 1R→BE, 2R→+1R. Per-symbol target ext.",
            },
          ].map(s => (
            <div key={s.step} style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "flex-start" }}>
              <div style={{ width: 28, height: 28, borderRadius: "50%", background: s.color, color: "#000", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 11, flexShrink: 0, marginTop: 2 }}>{s.step}</div>
              <div style={{ flex: 1, background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ color: s.color, fontWeight: 700, fontSize: 12, marginBottom: 6 }}>{s.title}</div>
                <div style={{ display: "grid", gridTemplateColumns: "70px 1fr", gap: "4px 10px", fontSize: 10 }}>
                  <span style={{ color: COLORS.muted }}>INPUT</span><span style={{ color: COLORS.text }}>{s.input}</span>
                  <span style={{ color: COLORS.muted }}>PROCESS</span><span style={{ color: COLORS.text }}>{s.process}</span>
                  <span style={{ color: COLORS.muted }}>OUTPUT</span><span style={{ color: COLORS.green }}>{s.output}</span>
                  <span style={{ color: COLORS.muted }}>CHECK</span><span style={{ color: COLORS.yellow }}>{s.check}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

