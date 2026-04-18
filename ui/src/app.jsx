/* global React, ReactDOM, Sidebar, Topbar,
          RunStartScreen, RunLiveScreen, HitlScreen, HistoryScreen, ResourcesScreen, ReportScreen, WorkspaceScreen, Icon */
const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "default",
  "variation": "A"
}/*EDITMODE-END*/;

function GraphView({ nodes }) {
  const nodeList = nodes && nodes.length ? nodes : [
    { id: 1,   title: "Page Classifier",    status: "queued", x: 40,  y: 40  },
    { id: 1.5, title: "Structure Analyzer", status: "queued", x: 260, y: 40  },
    { id: 2,   title: "Journey Planner",    status: "queued", x: 480, y: 40  },
    { id: 3,   title: "Active Explorer",    status: "queued", x: 260, y: 180 },
    { id: 4,   title: "Manual Capture",     status: "queued", x: 480, y: 180 },
    { id: 5,   title: "Planning · HITL",    status: "queued", x: 260, y: 320 },
    { id: 6,   title: "GTM Creation",       status: "queued", x: 40,  y: 460 },
    { id: 7,   title: "Publish",            status: "queued", x: 260, y: 460 },
    { id: 8,   title: "Reporter",           status: "queued", x: 480, y: 460 },
  ];
  const POS = { 1:{ x:40,y:40 }, 1.5:{ x:260,y:40 }, 2:{ x:480,y:40 }, 3:{ x:260,y:180 }, 4:{ x:480,y:180 }, 5:{ x:260,y:320 }, 6:{ x:40,y:460 }, 7:{ x:260,y:460 }, 8:{ x:480,y:460 } };
  const edges = [[1,1.5],[1.5,2],[2,3],[3,4],[3,5],[4,5],[5,6],[6,7],[7,8]];
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title">LangGraph 뷰</div>
        <div className="panel-sub">StateGraph · 9 nodes</div>
      </div>
      <div className="panel-body" style={{ padding: 14 }}>
        <div className="graph">
          <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
            {edges.map(([a, b], i) => {
              const p = POS[a], q = POS[b];
              if (!p || !q) return null;
              const n = nodeList.find(x => x.id === a);
              const s = n ? n.status : "queued";
              const ax = p.x + 90, ay = p.y + 30, bx = q.x + 90, by = q.y + 30, mx = (ax + bx) / 2;
              return <path key={i} d={`M${ax} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${bx} ${by}`} className={`glink ${s}`} />;
            })}
          </svg>
          {nodeList.map(n => {
            const pos = POS[n.id] || { x: 0, y: 0 };
            return (
              <div key={n.id} className={`gnode ${n.status}`} style={{ left: pos.x, top: pos.y }}>
                <div className="t">node {n.id}</div>
                <div className="n">{n.title}</div>
                <div className="m">{n.status === "run" ? "● running" : n.status === "done" ? "✓ done" : n.status}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Tweaks({ open, onClose, density, setDensity, variation, setVariation }) {
  if (!open) return null;
  return (
    <div className="tweaks">
      <h4>Tweaks <span className="close" onClick={onClose}>✕</span></h4>
      <div className="row"><label>DENSITY</label></div>
      <div className="seg">
        {["tight", "default", "cozy"].map(d => (
          <button key={d} className={density === d ? "on" : ""} onClick={() => setDensity(d)}>
            {d === "tight" ? "조밀" : d === "cozy" ? "여유" : "기본"}
          </button>
        ))}
      </div>
      <div className="row" style={{ marginTop: 12 }}><label>VARIATION</label></div>
      <div className="seg" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        {["A", "C"].map(v => (
          <button key={v} className={variation === v ? "on" : ""} onClick={() => setVariation(v)}>{v}</button>
        ))}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 10, lineHeight: 1.5 }}>
        A · 기본 세로 타임라인<br />
        C · LangGraph 노드 그래프
      </div>
    </div>
  );
}

function App() {
  // runId: URL ?run= 파라미터로 관리
  const [runId, setRunId] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("run") || "";
  });

  const [route, setRoute] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("screen") || localStorage.getItem("gtm:route") || "start";
  });

  const [density, setDensity] = useState(TWEAK_DEFAULTS.density);
  const [variation, setVariation] = useState(TWEAK_DEFAULTS.variation);
  const [tweaksOpen, setTweaksOpen] = useState(false);

  useEffect(() => { document.body.dataset.density = density; }, [density]);
  useEffect(() => { localStorage.setItem("gtm:route", route); }, [route]);

  // URL 동기화
  const navigate = (newRunId, newRoute) => {
    const url = new URL(window.location.href);
    if (newRunId !== undefined) {
      if (newRunId) url.searchParams.set("run", newRunId);
      else url.searchParams.delete("run");
    }
    if (newRoute !== undefined) {
      url.searchParams.set("screen", newRoute);
    }
    window.history.pushState({}, "", url.toString());
    if (newRunId !== undefined) setRunId(newRunId);
    if (newRoute !== undefined) setRoute(newRoute);
  };

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

  const routeMap = { run: "live", history: "history", hitl: "hitl", resources: "resources", report: "report", workspace: "workspace" };
  const navRoute = Object.entries(routeMap).find(([, v]) => v === route)?.[0] || "run";
  const onNavRoute = (navKey) => navigate(undefined, routeMap[navKey]);

  const running = route === "live" && !!runId;

  // 항상 훅을 최상위에서 호출 (Rules of Hooks)
  const { state: runState, workspaceAsk } = window.useRunLog(runId);

  // 워크스페이스 상한 HITL 요청이 들어오면 Approvals 화면으로 자동 전환
  useEffect(() => {
    if (workspaceAsk && route !== "hitl") {
      navigate(undefined, "hitl");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceAsk]);

  // 에이전트 시작 콜백 — RunStartScreen에서 호출
  const handleStart = ({ runId: newRunId, navigate: navTarget }) => {
    navigate(newRunId, navTarget || "live");
  };

  // History에서 Run 선택
  const handleSelectRun = (selectedRunId) => {
    navigate(selectedRunId, "report");
  };

  let content, crumbs;
  const runLabel = runId ? `Run ${runId}` : "Run —";

  if (variation === "C") {
    crumbs = ["Workspace", runLabel, "Graph"];
    content = (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">LangGraph 다이어그램</h1>
            <div className="page-sub">Node 간 상태·엣지를 한눈에 확인</div>
          </div>
        </div>
        <GraphView nodes={runState.nodes} />
      </div>
    );
  } else {
    if (route === "start") {
      crumbs = ["Workspace", "New Run"];
      content = <RunStartScreen onStart={handleStart} />;
    } else if (route === "live") {
      crumbs = ["Workspace", runLabel, "Live"];
      content = <RunLiveScreen runId={runId} />;
    } else if (route === "hitl") {
      crumbs = ["Workspace", runLabel, "HITL"];
      content = <HitlScreen runId={runId} onApprove={() => navigate(undefined, "live")} />;
    } else if (route === "history") {
      crumbs = ["Workspace", "History"];
      content = <HistoryScreen onSelectRun={handleSelectRun} />;
    } else if (route === "resources") {
      crumbs = ["Workspace", runLabel, "Resources"];
      content = <ResourcesScreen runId={runId} />;
    } else if (route === "report") {
      crumbs = ["Workspace", runLabel, "Report"];
      content = <ReportScreen runId={runId} />;
    } else if (route === "workspace") {
      crumbs = ["Workspace", "관리"];
      content = <WorkspaceScreen />;
    } else {
      crumbs = ["Workspace", "New Run"];
      content = <RunStartScreen onStart={handleStart} />;
    }
  }

  const hitlWaiting = !!workspaceAsk
    || (runState.nodes || []).some(n => n.status === "hitl_wait");

  return (
    <div className="app-shell" data-screen-label="Main">
      <Sidebar route={navRoute} onRoute={onNavRoute} running={running} hitlWaiting={hitlWaiting} />
      <div className="main">
        <Topbar crumbs={crumbs}>
          <button className="btn ghost sm" onClick={() => navigate("", "start")}>
            <Icon name="plus" size={12} className="btn-ico" /> 새 Run
          </button>
          <div className="row tight" style={{ background: "var(--bg-sunken)", padding: "3px", borderRadius: 8, border: "1px solid var(--line)" }}>
            {["live", "hitl", "resources", "report"].map(k => (
              <button key={k}
                className="btn ghost sm"
                style={{
                  padding: "4px 10px",
                  background: route === k ? "var(--panel)" : "transparent",
                  boxShadow: route === k ? "var(--sh-1)" : "none",
                  color: route === k ? "var(--ink-1)" : "var(--ink-3)",
                }}
                onClick={() => navigate(undefined, k)}>
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
