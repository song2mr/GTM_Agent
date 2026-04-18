/* global React */
const { useState, useEffect, useMemo } = React;

// ── Tiny inline icons (stroke-based, neutral) ─────────────────────────────
const Icon = ({ name, size = 16, className = "" }) => {
  const s = { width: size, height: size, fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    home: <><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></>,
    run: <><circle cx="12" cy="12" r="9" /><path d="M10 8l6 4-6 4z" /></>,
    history: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    report: <><path d="M6 3h9l3 3v15H6z" /><path d="M9 12h6M9 16h6M9 8h3" /></>,
    resources: <><rect x="3" y="5" width="18" height="4" rx="1" /><rect x="3" y="11" width="18" height="4" rx="1" /><rect x="3" y="17" width="12" height="4" rx="1" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2L14 3h-4l-.6 2.6a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2 1.2L10 21h4l.6-2.6a7 7 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" /></>,
    play: <path d="M8 5l12 7-12 7z" />,
    pause: <><rect x="7" y="5" width="4" height="14" /><rect x="13" y="5" width="4" height="14" /></>,
    chevron: <path d="M9 18l6-6-6-6" />,
    check: <path d="M5 13l4 4 10-10" />,
    x: <path d="M6 6l12 12M6 18L18 6" />,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M4 16V5a1 1 0 0 1 1-1h11" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="M21 21l-5-5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <><path d="M5 12h14" /><path d="M13 5l7 7-7 7" /></>,
    zap: <path d="M13 3L4 14h7l-1 7 9-11h-7z" />,
    code: <><path d="M8 6l-6 6 6 6" /><path d="M16 6l6 6-6 6" /></>,
    dot: <circle cx="12" cy="12" r="4" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
    external: <><path d="M14 4h6v6" /><path d="M10 14l10-10" /><path d="M20 14v6H4V4h6" /></>,
    beaker: <><path d="M9 3h6" /><path d="M10 3v5l-5 11a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3L14 8V3" /></>,
    sparkle: <><path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" /></>,
    filter: <path d="M3 5h18l-7 9v6l-4-2v-4z" />,
    trash: <><path d="M4 7h16" /><path d="M10 11v6M14 11v6" /><path d="M6 7l1 13h10l1-13" /><path d="M9 7V4h6v3" /></>,
  };
  return <svg viewBox="0 0 24 24" style={s} className={className}>{paths[name] || null}</svg>;
};

// ── Sidebar ──────────────────────────────────────────────────────────────
function Sidebar({ route, onRoute, running }) {
  const { activeWorkspace, workspaces } = window.useWorkspaces();
  const wsLabel = activeWorkspace ? activeWorkspace.name : (workspaces.length === 0 ? "워크스페이스 없음" : "선택 안 됨");
  const wsCount = activeWorkspace ? (activeWorkspace.containerId || "—") : null;

  const items = [
    { key: "run",      label: "Run",        icon: "run",       count: running ? "●" : "" },
    { key: "history",  label: "History",    icon: "history",   count: "" },
    { key: "hitl",     label: "Approvals",  icon: "sparkle",   count: "" },
    { key: "resources",label: "Resources",  icon: "resources", count: "" },
    { key: "report",   label: "Report",     icon: "report",    count: "" },
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">G</div>
        <div>
          <div className="brand-title">GTM AI</div>
          <div className="brand-sub">control room</div>
        </div>
      </div>
      <div className="nav-section-label">워크스페이스</div>
      <div className="nav-item" aria-current={route === "workspace"}
           onClick={() => onRoute("workspace")}
           style={{ cursor: "pointer" }}>
        <Icon name="home" className="ico" />
        <span className="nowrap" style={{ flex: 1, minWidth: 0 }}>{wsLabel}</span>
        {wsCount ? <span className="count mono" style={{ fontSize: 10.5 }}>{wsCount.slice(0, 12)}</span> : null}
      </div>

      <div className="nav-section-label">에이전트</div>
      {items.map(it => (
        <div key={it.key} className="nav-item" aria-current={route === it.key}
             onClick={() => onRoute(it.key)}>
          <Icon name={it.icon} className="ico" />
          <span>{it.label}</span>
          {it.count ? <span className="count">{it.count}</span> : null}
        </div>
      ))}

      <div className="nav-section-label">시스템</div>
      <div className="nav-item" style={{ opacity: 0.45, cursor: "default" }}>
        <Icon name="settings" className="ico" /><span>설정</span>
      </div>
      <div className="nav-item" style={{ opacity: 0.45, cursor: "default" }}>
        <Icon name="beaker" className="ico" /><span>실험 모드</span><span className="count mono">β</span>
      </div>

      <div className="sidebar-footer">
        <span className={`dot ${running ? "" : "idle"}`} />
        {running ? <>에이전트 실행 중</> : <>대기 중</>}
      </div>
    </aside>
  );
}

// ── Topbar ───────────────────────────────────────────────────────────────
function Topbar({ crumbs, children }) {
  return (
    <div className="topbar">
      <div className="crumbs">
        {crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 ? <span className="sep">/</span> : null}
            {i === crumbs.length - 1 ? <b>{c}</b> : <span>{c}</span>}
          </React.Fragment>
        ))}
      </div>
      <div className="topbar-actions">{children}</div>
    </div>
  );
}

// ── Vertical timeline ────────────────────────────────────────────────────
function Timeline({ nodes, activeId, onSelect }) {
  return (
    <div className="timeline">
      <div className="timeline-head">
        <h3>Node 진행 상황</h3>
        <span className="muted-mono">
          {nodes.filter(n => ["done", "skip", "failed"].includes(n.status)).length}/{nodes.length}
        </span>
      </div>
      <div className="tl-list">
        {nodes.map((n, i) => (
          <div key={n.id} className={`tl-node ${n.status} ${n.id === activeId ? "active" : ""}`}
               onClick={() => onSelect && onSelect(n.id)}>
            <div className="tl-spine">
              <div className={`tl-bullet ${n.status === "skip" ? "skip" : n.status}`}>
                {n.status === "done" ? "✓" : n.status === "skip" ? "−" : String(n.id)}
              </div>
              {i < nodes.length - 1 ? <div className="tl-line" /> : null}
            </div>
            <div>
              <div className="tl-title">
                {n.title}
                {n.status === "run" ? <span className="chip accent"><span className="mini-dot" />running</span> : null}
                {n.status === "queued" ? <span className="chip">queued</span> : null}
                {n.status === "skip" ? <span className="chip">생략</span> : null}
                {n.status === "failed" ? <span className="chip danger">failed</span> : null}
              </div>
              <div className="tl-desc">{n.sub}</div>
            </div>
            <div className="tl-side">
              <div>{n.duration}</div>
              <div style={{ color: "var(--ink-4)" }}>{n.tokens}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Thought bubbles ──────────────────────────────────────────────────────
function Thoughts({ items, typing }) {
  return (
    <div className="thoughts">
      {items.map((t, i) => (
        <div className="thought" key={i}>
          <div className={`who ${t.who}`}>
            {t.who === "agent" ? "AI" : t.who === "tool" ? "⚙" : "U"}
          </div>
          <div className={`bubble ${t.who}`}>
            <div className="meta">
              <b>{t.label}</b>
              <span>{t.time}</span>
            </div>
            {t.kind === "tool" ? <code className="mono" style={{ fontSize: 12 }}>{t.text}</code> : <div>{t.text}</div>}
          </div>
        </div>
      ))}
      {typing ? (
        <div className="thought">
          <div className="who agent">AI</div>
          <div className="bubble agent typing">
            <div className="meta"><b>Navigator</b><span>지금</span></div>
            <span>장바구니 담기 후 dataLayer 응답을 기다리는 중</span>
            <span className="cursor" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── JSON pretty-print (simple, original, lightweight) ───────────────────
function Json({ value }) {
  const render = (v, indent = 0) => {
    const pad = "  ".repeat(indent);
    if (v === null) return <span className="n">null</span>;
    if (typeof v === "string") return <span className="s">"{v}"</span>;
    if (typeof v === "number") return <span className="n">{v}</span>;
    if (typeof v === "boolean") return <span className="n">{String(v)}</span>;
    if (Array.isArray(v)) {
      return (
        <>
          <span className="p">[</span>{"\n"}
          {v.map((item, i) => (
            <React.Fragment key={i}>
              {pad}  {render(item, indent + 1)}{i < v.length - 1 ? <span className="p">,</span> : null}{"\n"}
            </React.Fragment>
          ))}
          {pad}<span className="p">]</span>
        </>
      );
    }
    if (typeof v === "object") {
      const keys = Object.keys(v);
      return (
        <>
          <span className="p">{"{"}</span>{"\n"}
          {keys.map((k, i) => (
            <React.Fragment key={k}>
              {pad}  <span className="k">"{k}"</span><span className="p">: </span>{render(v[k], indent + 1)}
              {i < keys.length - 1 ? <span className="p">,</span> : null}{"\n"}
            </React.Fragment>
          ))}
          {pad}<span className="p">{"}"}</span>
        </>
      );
    }
    return <span>{String(v)}</span>;
  };
  return <pre className="json-view">{render(value)}</pre>;
}

// ── Simple markdown renderer (enough for report.md) ─────────────────────
function Markdown({ source }) {
  const html = useMemo(() => {
    const lines = source.split("\n");
    let out = "";
    let inTable = false;
    let inList = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.startsWith("# "))      out += `<h1>${esc(line.slice(2))}</h1>`;
      else if (line.startsWith("## "))  out += `<h2>${esc(line.slice(3))}</h2>`;
      else if (line.startsWith("### ")) out += `<h3>${esc(line.slice(4))}</h3>`;
      else if (line.startsWith("- ")) {
        if (!inList) { out += "<ul>"; inList = true; }
        out += `<li>${inline(line.slice(2))}</li>`;
      } else if (line.startsWith("|")) {
        if (!inTable) { out += "<table>"; inTable = true; }
        const cells = line.split("|").slice(1, -1).map(c => c.trim());
        if (cells.every(c => /^[-: ]+$/.test(c))) continue;
        const tag = inTable && out.endsWith("<table>") ? "th" : "td";
        out += "<tr>" + cells.map(c => `<${tag}>${inline(c)}</${tag}>`).join("") + "</tr>";
      } else {
        if (inList) { out += "</ul>"; inList = false; }
        if (inTable) { out += "</table>"; inTable = false; }
        if (line.trim() === "") out += "";
        else out += `<p>${inline(line)}</p>`;
      }
    }
    if (inList) out += "</ul>";
    if (inTable) out += "</table>";
    return out;
    function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
    function inline(s) {
      return esc(s)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
    }
  }, [source]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}

Object.assign(window, { Icon, Sidebar, Topbar, Timeline, Thoughts, Json, Markdown });
