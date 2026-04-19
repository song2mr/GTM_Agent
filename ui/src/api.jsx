/* global React */
// ui/src/api.jsx — logs/{run_id}/ 폴더를 polling으로 구독하는 훅

const POLL_MS = 1500;

/** 백엔드 ISO ts(UTC …Z) → 한국 표준시 시각 문자열 HH:mm:ss */
function formatTimeKst(iso) {
  if (!iso || typeof iso !== "string") return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.length >= 19 ? iso.slice(11, 19) : "—";
  return d.toLocaleTimeString("sv-SE", { timeZone: "Asia/Seoul", hour12: false });
}

window.useRunLog = function useRunLog(runId) {
  const [state, setState] = React.useState({ nodes: [], status: "loading" });
  const [events, setEvents] = React.useState([]);   // datalayer_event 목록
  const [thoughts, setThoughts] = React.useState([]);
  const [plan, setPlan] = React.useState(null);
  const [planMeta, setPlanMeta] = React.useState({ normalize_errors: [], canplan_hash: "" });
  const [workspaceAsk, setWorkspaceAsk] = React.useState(null); // {kind:"workspace_full", workspaces, current_count, limit, default_reuse_id, message}
  const [publishResult, setPublishResult] = React.useState(null);
  const offsetRef = React.useRef(0);
  const lastNodeKeyRef = React.useRef("");

  const base = `../logs/${runId}`;

  React.useEffect(() => {
    if (!runId) return;
    let alive = true;
    offsetRef.current = 0;
    lastNodeKeyRef.current = "";
    setEvents([]);
    setThoughts([]);
    setPlan(null);
    setPlanMeta({ normalize_errors: [], canplan_hash: "" });
    setWorkspaceAsk(null);
    setPublishResult(null);
    setState({ nodes: [], status: "loading" });

    async function tick() {
      // 1) state.json — 스냅샷
      try {
        const s = await fetch(`${base}/state.json`, { cache: "no-store" });
        if (s.ok) setState(await s.json());
      } catch (_) {}

      // 2) events.jsonl — 증분 읽기
      try {
        const r = await fetch(`${base}/events.jsonl`, { cache: "no-store" });
        if (r.ok) {
          const txt = await r.text();
          const newPart = txt.slice(offsetRef.current);
          offsetRef.current = txt.length;
          const lines = newPart.split("\n").filter(Boolean);
          for (const line of lines) {
            let ev;
            try { ev = JSON.parse(line); } catch { continue; }
            if (ev.type === "node_enter" && ev.node_key) {
              lastNodeKeyRef.current = ev.node_key;
            } else if (ev.type === "datalayer_event") {
              setEvents(cur => [...cur, {
                t: formatTimeKst(ev.ts),
                event: ev.event,
                url: ev.url,
                source: ev.source,
                params: ev.params,
              }]);
            } else if (ev.type === "thought") {
              setThoughts(cur => [...cur, {
                who: ev.who,
                label: ev.label,
                time: formatTimeKst(ev.ts),
                kind: ev.kind || "plain",
                text: ev.text,
                nodeKey: lastNodeKeyRef.current || undefined,
              }]);
            } else if (ev.type === "hitl_request") {
              const kind = ev.kind || "plan";
              if (kind === "workspace_full") {
                setWorkspaceAsk({
                  kind: "workspace_full",
                  workspaces: ev.workspaces || [],
                  current_count: ev.current_count || 0,
                  limit: ev.limit || 3,
                  default_reuse_id: ev.default_reuse_id || "",
                  message: ev.message || "",
                });
              } else {
                setPlan(ev.plan);
                setPlanMeta({
                  normalize_errors: ev.normalize_errors || [],
                  canplan_hash: ev.canplan_hash || (ev.plan && ev.plan.canplan_hash) || "",
                });
              }
            } else if (ev.type === "hitl_decision") {
              // 결정이 내려지면 workspace_full 카드는 닫는다
              setWorkspaceAsk(null);
            } else if (ev.type === "publish_result") {
              setPublishResult({
                success: ev.success,
                version_id: ev.version_id,
                warning: ev.warning,
              });
            }
          }
        }
      } catch (_) {}

      if (alive) setTimeout(tick, POLL_MS);
    }

    tick();
    return () => { alive = false; };
  }, [runId]);

  return { state, events, thoughts, plan, planMeta, workspaceAsk, publishResult };
};

window.useHistory = function useHistory() {
  const [items, setItems] = React.useState([]);
  React.useEffect(() => {
    function load() {
      fetch("../logs/index.json", { cache: "no-store" })
        .then(r => r.ok ? r.json() : [])
        .then(setItems)
        .catch(() => setItems([]));
    }
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);
  return items;
};

window.useWorkspaces = function useWorkspaces() {
  const load = () => { try { return JSON.parse(localStorage.getItem("gtm:workspaces") || "[]"); } catch { return []; } };
  const [workspaces, setWorkspaces] = React.useState(load);
  const [activeId, setActiveIdState] = React.useState(() => localStorage.getItem("gtm:activeWorkspace") || "");

  const persist = (ws) => { setWorkspaces(ws); localStorage.setItem("gtm:workspaces", JSON.stringify(ws)); };

  const add = (ws) => {
    const id = Date.now().toString();
    const next = [...workspaces, { ...ws, id, createdAt: new Date().toISOString() }];
    persist(next);
    return id;
  };
  const update = (id, patch) => persist(workspaces.map(w => w.id === id ? { ...w, ...patch } : w));
  const remove = (id) => {
    persist(workspaces.filter(w => w.id !== id));
    if (activeId === id) { localStorage.removeItem("gtm:activeWorkspace"); setActiveIdState(""); }
  };
  const setActive = (id) => {
    const ws = workspaces.find(w => w.id === id);
    if (!ws) return;
    localStorage.setItem("gtm:activeWorkspace", id);
    setActiveIdState(id);
    // gtm:config 동기화 → RunStartScreen 폼 자동 반영
    const prev = (() => { try { return JSON.parse(localStorage.getItem("gtm:config") || "{}"); } catch { return {}; } })();
    localStorage.setItem("gtm:config", JSON.stringify({
      ...prev,
      url: ws.defaultUrl || prev.url || "",
      accountId: ws.accountId || "",
      containerId: ws.containerId || "",
      workspaceId: ws.gtmWorkspaceId || "",
    }));
  };
  const activeWorkspace = workspaces.find(w => w.id === activeId) || null;
  return { workspaces, activeId, activeWorkspace, add, update, remove, setActive };
};

window.useReport = function useReport(runId) {
  const [md, setMd] = React.useState("");
  React.useEffect(() => {
    if (!runId) return;
    let alive = true;
    function load() {
      fetch(`../logs/${runId}/report.md`, { cache: "no-store" })
        .then(r => r.ok ? r.text() : "")
        .then(txt => { if (alive) setMd(txt); });
    }
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [runId]);
  return md;
};
