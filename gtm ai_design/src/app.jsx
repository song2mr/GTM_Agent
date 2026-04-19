/* global React, ReactDOM, Sidebar, Topbar,
          RunStartScreen, RunLiveScreen, HitlScreen, HistoryScreen, ResourcesScreen, ReportScreen, Icon */
const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "default",
  "variation": "B"
}/*EDITMODE-END*/;

// Variation labels:
// A — 기본 세로 타임라인
// B — 타임라인 + Playwright 라이브 브라우저 뷰 (Split)
// C — 노드 그래프 (LangGraph 다이어그램)
// D — 챗 중심 압축 뷰

function GraphView() {
  const nodes = [
    { id: 1,   label: "Page Classifier",   x: 40,  y: 40,  status: "done" },
    { id: 1.5, label: "Structure Analyzer",x: 260, y: 40,  status: "done" },
    { id: 2,   label: "Journey Planner",   x: 480, y: 40,  status: "done" },
    { id: 3,   label: "Active Explorer",   x: 260, y: 180, status: "run"  },
    { id: 4,   label: "Manual Capture",    x: 480, y: 180, status: "queued" },
    { id: 5,   label: "Planning · HITL",   x: 260, y: 320, status: "queued" },
    { id: 6,   label: "GTM Creation",      x: 40,  y: 460, status: "queued" },
    { id: 7,   label: "Publish",           x: 260, y: 460, status: "queued" },
    { id: 8,   label: "Reporter",          x: 480, y: 460, status: "queued" },
  ];
  const edges = [
    [1, 1.5, "done"], [1.5, 2, "done"], [2, 3, "run"],
    [3, 4, "queued"], [3, 5, "queued"], [4, 5, "queued"],
    [5, 6, "queued"], [6, 7, "queued"], [7, 8, "queued"],
  ];
  const pos = (id) => nodes.find(n => n.id === id);
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title">LangGraph 뷰</div>
        <div className="panel-sub">StateGraph · 9 nodes · 9 edges</div>
      </div>
      <div className="panel-body" style={{ padding: 14 }}>
        <div className="graph">
          <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
            {edges.map(([a, b, s], i) => {
              const p = pos(a), q = pos(b);
              const ax = p.x + 90, ay = p.y + 30;
              const bx = q.x + 90, by = q.y + 30;
              const mx = (ax + bx) / 2;
              return <path key={i} d={`M${ax} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${bx} ${by}`}
                           className={`glink ${s}`} />;
            })}
          </svg>
          {nodes.map(n => (
            <div key={n.id} className={`gnode ${n.status}`} style={{ left: n.x, top: n.y }}>
              <div className="t">node {n.id}</div>
              <div className="n">{n.label}</div>
              <div className="m">{n.status === "run" ? "● running" : n.status === "done" ? "✓ done" : "queued"}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ChatScreen() {
  return (
    <div className="page" style={{ maxWidth: 880, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">에이전트와 대화</h1>
          <div className="page-sub">평소처럼 말하면 됩니다. 중요한 순간에만 UI가 나타납니다.</div>
        </div>
      </div>
      <div className="chat-wrap">
        <div className="thought"><div className="who user">U</div>
          <div className="bubble user"><div className="meta"><b>you</b><span>09:22:14</span></div>
            shop.leekorea.co.kr에 GA4 이커머스 이벤트 전체 깔아줘. G-KX82JQ4M1P 써서.
          </div></div>
        <div className="thought"><div className="who agent">AI</div>
          <div className="bubble agent"><div className="meta"><b>에이전트</b><span>09:22:16</span></div>
            알겠습니다. 페이지 로드 후 dataLayer 상태 먼저 확인하고 탐색 큐를 구성할게요.
            purchase 이벤트는 어떻게 할까요? <div className="row tight" style={{ marginTop: 8 }}>
              <button className="btn sm">직접 캡처</button>
              <button className="btn sm">표준 스키마 승인</button>
              <button className="btn sm">스킵</button>
            </div>
          </div></div>
        <div className="thought"><div className="who user">U</div>
          <div className="bubble user"><div className="meta"><b>you</b><span>09:22:32</span></div>스킵</div></div>
        <div className="thought"><div className="who tool">⚙</div>
          <div className="bubble tool"><div className="meta"><b>playwright.navigate</b><span>09:22:35</span></div>
            <code className="mono" style={{ fontSize: 12 }}>GET /category/best → 200 · view_item_list 캡처됨</code>
          </div></div>
        <div className="thought"><div className="who agent">AI</div>
          <div className="bubble agent"><div className="meta"><b>에이전트</b><span>09:23:02</span></div>
            6개 이벤트 모두 캡처했어요. 설계안을 만들었습니다:
            <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
              <span className="chip accent">+6 Variables · +6 Triggers · +6 Tags · ↻ 1 update</span>
            </div>
            <div className="row tight" style={{ marginTop: 10 }}>
              <button className="btn sm">상세 보기</button>
              <button className="btn sm approve"><Icon name="check" size={10} className="btn-ico" />승인하고 생성</button>
            </div>
          </div></div>
      </div>
      <div className="chat-composer">
        <input placeholder="에이전트에게 말하기..." />
        <button className="btn ghost sm">⌘↵</button>
        <button className="btn primary sm"><Icon name="arrow" size={12} className="btn-ico" /></button>
      </div>
    </div>
  );
}

function Tweaks({ open, onClose, density, setDensity, variation, setVariation }) {
  if (!open) return null;
  return (
    <div className="tweaks">
      <h4>Tweaks <span className="close" onClick={onClose}>✕</span></h4>
      <div className="row">
        <label>DENSITY</label>
      </div>
      <div className="seg">
        {["tight", "default", "cozy"].map(d => (
          <button key={d} className={density === d ? "on" : ""} onClick={() => setDensity(d)}>
            {d === "tight" ? "조밀" : d === "cozy" ? "여유" : "기본"}
          </button>
        ))}
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <label>VARIATION</label>
      </div>
      <div className="seg" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        {["A", "B", "C", "D"].map(v => (
          <button key={v} className={variation === v ? "on" : ""} onClick={() => setVariation(v)}>{v}</button>
        ))}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 10, lineHeight: 1.5 }}>
        A · 기본 세로 타임라인<br />
        B · 타임라인 + 브라우저 라이브 뷰<br />
        C · LangGraph 노드 그래프<br />
        D · 챗 중심 압축 뷰
      </div>
    </div>
  );
}

function App() {
  const [route, setRoute] = useState(() => localStorage.getItem("gtm:route") || "live");
  const [density, setDensity] = useState(TWEAK_DEFAULTS.density);
  const [variation, setVariation] = useState(TWEAK_DEFAULTS.variation);
  const [tweaksOpen, setTweaksOpen] = useState(false);

  useEffect(() => {
    document.body.dataset.density = density;
  }, [density]);
  useEffect(() => { localStorage.setItem("gtm:route", route); }, [route]);

  // Tweaks host protocol
  useEffect(() => {
    const onMsg = (e) => {
      if (e.data?.type === "__activate_edit_mode") setTweaksOpen(true);
      if (e.data?.type === "__deactivate_edit_mode") setTweaksOpen(false);
    };
    window.addEventListener("message", onMsg);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const persist = (k, v) => {
    window.parent.postMessage({ type: "__edit_mode_set_keys", edits: { [k]: v } }, "*");
  };
  const onDensity = (d) => { setDensity(d); persist("density", d); };
  const onVariation = (v) => { setVariation(v); persist("variation", v); };

  // Routes (mapped to sidebar items)
  const routeMap = {
    run: "live",
    history: "history",
    hitl: "hitl",
    resources: "resources",
    report: "report",
  };
  const navRoute = Object.entries(routeMap).find(([k, v]) => v === route)?.[0] || "run";

  const onRoute = (navKey) => setRoute(routeMap[navKey]);

  const running = route === "live";

  let content, crumbs;
  if (variation === "C") {
    crumbs = ["Workspace", "Run 20260418_092214", "Graph"];
    content = (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">LangGraph 다이어그램</h1>
            <div className="page-sub">Node 간 상태·엣지를 한눈에 확인</div>
          </div>
        </div>
        <GraphView />
      </div>
    );
  } else if (variation === "D") {
    crumbs = ["Workspace", "Chat"];
    content = <ChatScreen />;
  } else {
    // A or B
    if (route === "start") { crumbs = ["Workspace", "New Run"]; content = <RunStartScreen onStart={() => setRoute("live")} />; }
    else if (route === "live") { crumbs = ["Workspace", "Run 20260418_092214", "Live"]; content = <RunLiveScreen variation={variation} />; }
    else if (route === "hitl") { crumbs = ["Workspace", "Run 20260418_092214", "HITL"]; content = <HitlScreen onApprove={() => setRoute("resources")} />; }
    else if (route === "history") { crumbs = ["Workspace", "History"]; content = <HistoryScreen />; }
    else if (route === "resources") { crumbs = ["Workspace", "Run 20260418_092214", "Resources"]; content = <ResourcesScreen />; }
    else if (route === "report") { crumbs = ["Workspace", "Run 20260418_092214", "Report"]; content = <ReportScreen />; }
    else { crumbs = ["Workspace"]; content = <RunStartScreen onStart={() => setRoute("live")} />; }
  }

  return (
    <div className="app-shell" data-screen-label="Main">
      <Sidebar route={navRoute} onRoute={onRoute} running={running} />
      <div className="main">
        <Topbar crumbs={crumbs}>
          <button className="btn ghost sm" onClick={() => setRoute("start")}>
            <Icon name="plus" size={12} className="btn-ico" /> 새 Run
          </button>
          <div className="row tight" style={{ background: "var(--bg-sunken)", padding: "3px", borderRadius: 8, border: "1px solid var(--line)" }}>
            {["live", "hitl", "resources", "report"].map(k => (
              <button key={k}
                className={`btn ghost sm ${route === k ? "" : ""}`}
                style={{
                  padding: "4px 10px",
                  background: route === k ? "var(--panel)" : "transparent",
                  boxShadow: route === k ? "var(--sh-1)" : "none",
                  color: route === k ? "var(--ink-1)" : "var(--ink-3)",
                }}
                onClick={() => setRoute(k)}>
                {k === "live" ? "Live" : k === "hitl" ? "HITL" : k === "resources" ? "GTM" : "Report"}
              </button>
            ))}
          </div>
          <button className="btn ghost sm" onClick={() => setTweaksOpen(v => !v)}>
            <Icon name="settings" size={12} className="btn-ico" />Tweaks
          </button>
        </Topbar>
        {content}
      </div>
      <Tweaks
        open={tweaksOpen}
        onClose={() => setTweaksOpen(false)}
        density={density} setDensity={onDensity}
        variation={variation} setVariation={onVariation}
      />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
