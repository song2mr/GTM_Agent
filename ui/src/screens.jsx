/* global React, Icon, Timeline, Thoughts, Json, Markdown */
const { useState, useEffect } = React;

// ── 1. Run Start screen ─────────────────────────────────────────────────
function RunStartScreen({ onStart }) {
  const saved = (() => { try { return JSON.parse(localStorage.getItem("gtm:config") || "{}"); } catch { return {}; } })();
  const [url, setUrl] = useState(saved.url || "https://shop.leekorea.co.kr");
  const [req, setReq] = useState(saved.req || "GA4 이커머스 이벤트 전체 설정 (view_item_list, view_item, add_to_cart, add_to_wishlist, view_cart, begin_checkout)");
  const [tag, setTag] = useState(saved.tag || "GA4");
  const [accountId, setAccountId] = useState(saved.accountId || "");
  const [containerId, setContainerId] = useState(saved.containerId || "");
  const [workspaceId, setWorkspaceId] = useState(saved.workspaceId || "");
  const [measurementId, setMeasurementId] = useState(saved.measurementId || "");
  const [rememberCreds, setRememberCreds] = useState(saved.rememberCreds !== false);
  const [credsOpen, setCredsOpen] = useState(!(saved.accountId && saved.containerId));
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const persistAndStart = async () => {
    if (rememberCreds) {
      localStorage.setItem("gtm:config", JSON.stringify({
        url, req, tag, accountId, containerId, workspaceId, measurementId, rememberCreds,
      }));
    } else {
      localStorage.removeItem("gtm:config");
    }
    setStarting(true);
    setError("");
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_url: url,
          user_request: req,
          tag_type: tag,
          account_id: accountId,
          container_id: containerId,
          workspace_id: workspaceId,
          measurement_id: measurementId,
        }),
      });
      const data = await res.json();
      if (data.run_id) {
        onStart && onStart({ runId: data.run_id });
      } else {
        setError(data.error || "실행 실패");
      }
    } catch (e) {
      setError(`서버 연결 실패: ${e.message}`);
    }
    setStarting(false);
  };

  const canStart = url && req && accountId && containerId && !starting;

  const history = window.useHistory();
  const lastRun = history[0];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">새 Run 시작</h1>
          <div className="page-sub">자연어로 요청하세요. 에이전트가 페이지를 탐색해 GTM을 설계·생성합니다.</div>
        </div>
        <div className="row tight">
          {lastRun ? <span className="chip"><Icon name="clock" size={12} /> 마지막 Run · {lastRun.t ? lastRun.t.slice(0, 16) : "—"}</span> : null}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="panel-title">
            <Icon name="sparkle" size={14} />
            GTM 연결
            {accountId && containerId
              ? <span className="chip accent"><span className="mini-dot" />구성 완료</span>
              : <span className="chip warn">미입력</span>}
          </div>
          <button className="btn ghost sm" onClick={() => setCredsOpen(o => !o)}>
            {credsOpen ? "접기" : "펼치기"}
          </button>
        </div>
        {credsOpen ? (
          <div className="panel-body" style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div className="field">
                <label>GTM_ACCOUNT_ID</label>
                <input className="input mono" placeholder="6123847219"
                       value={accountId} onChange={e => setAccountId(e.target.value)} />
              </div>
              <div className="field">
                <label>GTM_CONTAINER_ID</label>
                <input className="input mono" placeholder="208905963"
                       value={containerId} onChange={e => setContainerId(e.target.value)} />
              </div>
              <div className="field">
                <label>GTM_WORKSPACE_ID (선택)</label>
                <input className="input mono" placeholder="비워두면 자동으로 신규 생성"
                       value={workspaceId} onChange={e => setWorkspaceId(e.target.value)} />
              </div>
              <div className="field">
                <label>매체 트래킹 ID (선택)</label>
                <input className="input mono" placeholder="G-XXXXXXXX / 픽셀 ID / 계정 ID"
                       value={measurementId} onChange={e => setMeasurementId(e.target.value)} />
              </div>
            </div>
            <label className="row tight" style={{ cursor: "pointer", fontSize: 12.5, color: "var(--ink-2)" }}>
              <input type="checkbox" checked={rememberCreds}
                     onChange={e => setRememberCreds(e.target.checked)} />
              이 브라우저에 기억 <span className="muted-mono">(localStorage · 이 기기에서만)</span>
            </label>
            <div className="muted-mono" style={{ fontSize: 11.5 }}>
              OAuth 토큰(<code className="mono">credentials/token.json</code>)은 서버에서 관리됩니다.
            </div>
          </div>
        ) : (
          <div className="panel-body">
            <div className="row tight" style={{ flexWrap: "wrap", gap: 10 }}>
              <span className="chip"><span className="dim">account</span>&nbsp;{accountId || "—"}</span>
              <span className="chip"><span className="dim">container</span>&nbsp;{containerId || "—"}</span>
              <span className="chip"><span className="dim">workspace</span>&nbsp;{workspaceId || "자동 생성"}</span>
              {measurementId ? <span className="chip accent"><span className="dim">MID</span>&nbsp;{measurementId}</span> : null}
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="panel-title">요청</div>
          <div className="panel-sub">자연어 · 이벤트 목록 · 특수 요건</div>
        </div>
        <div className="panel-body" style={{ display: "grid", gap: 16 }}>
          <div className="field">
            <label>TARGET_URL</label>
            <input className="input mono" value={url} onChange={e => setUrl(e.target.value)} />
          </div>
          <div className="field">
            <label>USER_REQUEST</label>
            <textarea className="textarea" value={req} onChange={e => setReq(e.target.value)} />
            <div className="muted-mono">
              Measurement ID는 위 필드에서 입력하면 Constant 변수로 자동 주입됩니다.
            </div>
          </div>
          <div className="field">
            <label>TAG_TYPE</label>
            <div className="radio-row">
              {["GA4", "naver", "kakao"].map(t => (
                <div key={t} className={`radio-opt ${tag === t ? "on" : ""}`} onClick={() => setTag(t)}>
                  <span className="rmark" />
                  <span className="mono">{t}</span>
                  {t === "naver" || t === "kakao" ? <span className="chip">문서 fetch</span> : null}
                </div>
              ))}
            </div>
          </div>

          <div className="divider" />

          <div className="spread">
            <div className="row tight">
              <span className="chip"><Icon name="code" size={12} /> Node 1 → 8</span>
              <span className="chip"><Icon name="user" size={12} /> HITL Node 5</span>
            </div>
            <div className="row tight">
              <button className="btn primary" onClick={persistAndStart}
                      disabled={!canStart}
                      style={{ opacity: canStart ? 1 : 0.5, cursor: canStart ? "pointer" : "not-allowed" }}>
                {starting
                  ? <><span className="mini-dot" style={{ marginRight: 6 }} />시작 중...</>
                  : <><Icon name="play" size={12} className="btn-ico" />에이전트 실행</>}
              </button>
            </div>
          </div>
          {error ? (
            <div className="muted-mono" style={{ color: "var(--warn)", fontSize: 11.5 }}>{error}</div>
          ) : !canStart && !starting ? (
            <div className="muted-mono" style={{ color: "var(--warn)", fontSize: 11.5 }}>
              GTM_ACCOUNT_ID와 GTM_CONTAINER_ID는 필수입니다.
            </div>
          ) : null}
        </div>
      </div>

      {history.length > 0 ? (
        <div className="panel">
          <div className="panel-head"><div className="panel-title">최근 실행</div></div>
          <div className="panel-body" style={{ padding: 0 }}>
            <div className="history">
              {history.slice(0, 5).map((h, i) => (
                <div key={i} className="history-row" style={{ cursor: "pointer" }}
                     onClick={() => onStart && onStart({ runId: h.run_id, navigate: "live" })}>
                  <div className="tstamp">{h.t ? h.t.slice(0, 16) : "—"}</div>
                  <div><div className="urlcell">{h.url}</div></div>
                  <div className="mono" style={{ fontSize: 12.5 }}>{h.pageType} · {h.tagType}</div>
                  <div className="mono">{h.events}</div>
                  <div><span className={`chip ${h.status === "running" ? "accent" : h.status === "failed" ? "danger" : ""}`}>{h.status}</span></div>
                  <div className="mono" style={{ color: "var(--ink-3)", fontSize: 12 }}>{h.dur}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── 2. Live Agent Run view ──────────────────────────────────────────────
function RunLiveScreen({ runId }) {
  const { state, events, thoughts } = window.useRunLog(runId);
  const nodes = state.nodes || [];
  const [activeId, setActiveId] = useState(null);

  useEffect(() => { setActiveId(null); }, [runId]);

  const currentNodeId = state.current_node;
  const terminal = state.status === "done" || state.status === "failed";
  const defaultHighlightId = (() => {
    if (!nodes.length) return null;
    if (terminal) {
      const doneish = n =>
        n.status === "done" || n.status === "failed" || n.status === "skip";
      const last = [...nodes].reverse().find(doneish);
      return last ? last.id : nodes[nodes.length - 1].id;
    }
    return nodes[0] && nodes[0].id;
  })();
  const displayActiveId =
    activeId ?? currentNodeId ?? defaultHighlightId ?? (nodes[0] && nodes[0].id);

  const activeNode = nodes.find(n => n.id === displayActiveId) || nodes[0];

  const hasThoughtNodeKeys = thoughts.some(t => t.nodeKey);
  const thoughtsForNode = !hasThoughtNodeKeys
    ? thoughts
    : thoughts.filter(
        t => !t.nodeKey || (activeNode && t.nodeKey === activeNode.key),
      );

  if (!runId) {
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Live</h1>
            <div className="page-sub">실행 중인 Run이 없습니다. 새 Run을 시작하거나 History에서 선택하세요.</div>
          </div>
        </div>
      </div>
    );
  }

  const isRunning = state.status === "running";

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Run · {runId}</h1>
          <div className="page-sub mono">
            {state.target_url || "—"} · {state.tag_type || "—"} ·{" "}
            {isRunning
              ? <span style={{ color: "var(--accent-ink)" }}>실행 중</span>
              : state.status === "done" ? "완료"
              : state.status === "failed" ? <span style={{ color: "var(--danger)" }}>실패</span>
              : state.status || "대기"}
          </div>
        </div>
        <div className="row tight">
          {state.token_usage ? (
            <span className="token-usage">
              <span>in <b>{((state.token_usage.in || 0) / 1000).toFixed(1)}k</b></span>
              <span>out <b>{((state.token_usage.out || 0) / 1000).toFixed(1)}k</b></span>
              <span>$<b>{(state.token_usage.usd || 0).toFixed(3)}</b></span>
            </span>
          ) : null}
        </div>
      </div>

      <div className="run-grid">
        <Timeline nodes={nodes} activeId={displayActiveId} onSelect={id => setActiveId(id)} />

        <div className="detail">
          {activeNode ? (
            <div className="panel">
              <div className="panel-head">
                <div className="panel-title">
                  <span className="chip accent"><span className="mini-dot" />Node {activeNode.id}</span>
                  {activeNode.title}
                </div>
                <div className="panel-sub">{activeNode.status}</div>
              </div>
              <div className="panel-body">
                <Thoughts items={thoughtsForNode} typing={isRunning && activeNode && activeNode.status === "run"} />
              </div>
            </div>
          ) : null}


          <div className="panel">
            <div className="panel-head">
              <div className="panel-title">
                <span>dataLayer 캡처</span>
                <span className="chip accent"><span className="mini-dot" />{events.length} events</span>
              </div>
              <div className="panel-sub">window.__gtm_captured · live tail</div>
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              <div className="stream">
                {events.length === 0 ? (
                  <div style={{ padding: "16px 20px", color: "var(--ink-3)" }}>
                    {isRunning ? "캡처 대기 중..." : "캡처된 이벤트 없음"}
                  </div>
                ) : (
                  <table>
                    <thead><tr>
                      <th style={{ width: 100 }}>t</th>
                      <th style={{ width: 140 }}>event</th>
                      <th>url</th>
                      <th style={{ width: 90 }}>source</th>
                      <th>params</th>
                    </tr></thead>
                    <tbody>
                      {events.map((e, i) => (
                        <tr key={i} className={i === events.length - 1 ? "new" : ""}>
                          <td style={{ color: "var(--ink-3)" }}>{e.t}</td>
                          <td style={{ color: "var(--accent-ink)", fontWeight: 500 }}>{e.event}</td>
                          <td style={{ color: "var(--ink-2)" }}>{(e.url || "").slice(0, 60)}</td>
                          <td><span className="chip" style={{ padding: "1px 6px", fontSize: 10.5 }}>{e.source}</span></td>
                          <td style={{ color: "var(--ink-3)", fontSize: 11.5 }}>{JSON.stringify(e.params || {}).slice(0, 120)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 3. HITL Approval ────────────────────────────────────────────────────
function HitlScreen({ runId, onApprove }) {
  const { plan, state, workspaceAsk } = window.useRunLog(runId);
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [awaitingRedesign, setAwaitingRedesign] = useState(false);
  const [wsBusy, setWsBusy] = useState(false);
  const [wsSent, setWsSent] = useState(false);
  const [wsChoice, setWsChoice] = useState("");
  const prevPlanRef = React.useRef(null);

  // 새 workspace_full 요청이 오면 UI 상태 초기화
  React.useEffect(() => {
    if (workspaceAsk) {
      setWsSent(false);
      setWsChoice(workspaceAsk.default_reuse_id || "");
    }
  }, [workspaceAsk]);

  const sendWorkspaceDecision = async (decision) => {
    if (!runId || !workspaceAsk) return;
    setWsBusy(true);
    try {
      await fetch("/api/hitl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runId,
          kind: "workspace_full",
          decision, // "reuse" | "cancel"
          workspace_id: decision === "reuse" ? (wsChoice || workspaceAsk.default_reuse_id || "") : "",
        }),
      });
      setWsSent(true);
    } catch (e) {
      console.error("workspace HITL 전송 실패:", e);
    }
    setWsBusy(false);
  };

  // 재설계 후 새 plan이 도착하면 자동으로 화면 리셋
  useEffect(() => {
    if (!plan) return;
    if (prevPlanRef.current === null) {
      prevPlanRef.current = plan;
      return;
    }
    if (plan !== prevPlanRef.current) {
      prevPlanRef.current = plan;
      if (awaitingRedesign) {
        setSubmitted(false);
        setFeedback("");
        setAwaitingRedesign(false);
      }
    }
  }, [plan]);

  const sendHitl = async (approved) => {
    if (!runId) return;
    setSubmitting(true);
    try {
      await fetch("/api/hitl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, approved, feedback }),
      });
      if (approved) {
        onApprove && onApprove();
      } else {
        setAwaitingRedesign(true);
        setSubmitted(true);
      }
    } catch (e) {
      console.error("HITL 전송 실패:", e);
    }
    setSubmitting(false);
  };

  if (!runId) {
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Plan 검토 · HITL</h1>
            <div className="page-sub">실행 중인 Run이 없습니다.</div>
          </div>
        </div>
      </div>
    );
  }

  // 워크스페이스 상한 HITL — plan 검토보다 우선 표시
  if (workspaceAsk) {
    const wss = workspaceAsk.workspaces || [];
    const selectedId = wsChoice || workspaceAsk.default_reuse_id || (wss[0] && wss[0].workspaceId) || "";
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">GTM 작업공간 선택 · HITL</h1>
            <div className="page-sub">
              {workspaceAsk.message ||
                `워크스페이스가 ${workspaceAsk.current_count}/${workspaceAsk.limit} 로 가득 찼습니다.`}
            </div>
          </div>
          <div className="row tight">
            {wsSent
              ? <span className="chip"><Icon name="check" size={12} />응답 전송됨</span>
              : <span className="chip warn"><Icon name="clock" size={12} />사용자 결정 대기</span>}
          </div>
        </div>

        <div className="hitl">
          <div className="hitl-head">
            <span className="stamp">Node 6 · GTM Creation</span>
            <h3>작업공간 상한 도달</h3>
            <span style={{ marginLeft: "auto" }} className="muted-mono">{runId}</span>
          </div>
          <div className="hitl-body">
            <div className="kv-grid">
              <dt>현재 워크스페이스</dt><dd>{workspaceAsk.current_count} / {workspaceAsk.limit}</dd>
              <dt>기본 재사용 후보</dt>
              <dd>
                {(() => {
                  const d = wss.find(w => w.workspaceId === workspaceAsk.default_reuse_id);
                  return d ? `${d.name} (id=${d.workspaceId})` : "—";
                })()}
              </dd>
            </div>

            <div className="panel" style={{ boxShadow: "none" }}>
              <div className="panel-head">
                <div className="panel-title">
                  기존 작업공간 목록
                  <span className="chip">{wss.length}개</span>
                </div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table className="plan-table">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}></th>
                      <th>name</th>
                      <th>workspaceId</th>
                      <th>비고</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wss.map(w => (
                      <tr key={w.workspaceId}>
                        <td>
                          <input
                            type="radio"
                            name="ws-reuse"
                            disabled={wsSent || wsBusy}
                            checked={selectedId === w.workspaceId}
                            onChange={() => setWsChoice(w.workspaceId)}
                          />
                        </td>
                        <td>{w.name || "(이름 없음)"}</td>
                        <td className="mono">{w.workspaceId}</td>
                        <td>
                          {w.ai_managed ? <span className="chip accent">gtm-ai</span> : <span className="chip">사용자</span>}
                        </td>
                      </tr>
                    ))}
                    {wss.length === 0 ? (
                      <tr><td colSpan={4} style={{ padding: 12, color: "var(--ink-4)" }}>표시할 작업공간이 없습니다.</td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="row tight" style={{ justifyContent: "flex-end", gap: 8 }}>
              <button
                className="btn"
                disabled={wsBusy || wsSent}
                onClick={() => sendWorkspaceDecision("cancel")}
              >
                <Icon name="x" size={12} /> 실행 중단
              </button>
              <button
                className="btn primary"
                disabled={wsBusy || wsSent || !selectedId}
                onClick={() => sendWorkspaceDecision("reuse")}
              >
                <Icon name="check" size={12} /> 선택한 작업공간 재사용
              </button>
            </div>
            {wsSent ? (
              <div className="page-sub" style={{ marginTop: 8 }}>
                응답을 전송했습니다. 에이전트가 이어서 처리합니다.
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  if (!plan) {
    const isWaiting = (state.nodes || []).some(n => n.key === "planning" && n.status === "hitl_wait");
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Plan 검토 · HITL</h1>
            <div className="page-sub">
              {isWaiting
                ? "설계안 생성 완료 — 잠시 후 표시됩니다."
                : "Node 5 Planning이 완료되면 설계안이 표시됩니다."}
            </div>
          </div>
          {isWaiting ? <span className="chip warn"><Icon name="clock" size={12} />대기 중</span> : null}
        </div>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">Plan 검토 · HITL</h1>
            <div className="page-sub">
              {awaitingRedesign
                ? "피드백 전송 완료 — 에이전트가 재설계 중입니다. 새 설계안이 도착하면 자동으로 표시됩니다."
                : "응답 전송 완료. 에이전트가 처리 중입니다."}
            </div>
          </div>
          {awaitingRedesign
            ? <span className="chip warn"><Icon name="clock" size={12} />재설계 중</span>
            : null}
        </div>
      </div>
    );
  }

  const vars = plan.variables || [];
  const trigs = plan.triggers || [];
  const tags = plan.tags || [];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Plan 검토 · HITL</h1>
          <div className="page-sub">GTM에 반영하기 전, AI가 생성한 설계안을 확인하세요.</div>
        </div>
        <div className="row tight">
          <span className="chip warn"><Icon name="clock" size={12} />대기 중</span>
        </div>
      </div>

      <div className="hitl">
        <div className="hitl-head">
          <span className="stamp">Node 5 · Planning</span>
          <h3>GTM {state.tag_type || ""} 설계안</h3>
          <span style={{ marginLeft: "auto" }} className="muted-mono">{runId}</span>
        </div>
        <div className="hitl-body">
          <div className="kv-grid">
            <dt>Target</dt><dd>{state.target_url || "—"}</dd>
            <dt>Tag Type</dt><dd>{state.tag_type || "—"}</dd>
            <dt>Variables</dt><dd>{vars.length}개</dd>
            <dt>Triggers</dt><dd>{trigs.length}개</dd>
            <dt>Tags</dt><dd>{tags.length}개</dd>
          </div>

          {[
            { key: "variables", label: "Variables", list: vars },
            { key: "triggers",  label: "Triggers",  list: trigs },
            { key: "tags",      label: "Tags",       list: tags },
          ].map(({ key, label, list }) => (
            <div key={key} className="panel" style={{ boxShadow: "none" }}>
              <div className="panel-head">
                <div className="panel-title">
                  {label}
                  <span className="chip accent">+{list.length}</span>
                </div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table className="plan-table">
                  <thead>
                    <tr>
                      <th>name</th>
                      <th>type</th>
                      {key === "tags" ? <th>trigger</th> : null}
                      {key === "tags" ? <th>event parameters</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((r, i) => (
                      <tr key={i}>
                        <td className="name">{r.name}</td>
                        <td style={{ color: "var(--ink-3)" }}>{r.type}</td>
                        {key === "tags" ? (
                          <td className="mono" style={{ fontSize: 12 }}>
                            {(r.firing_trigger_names || []).join(", ") || "—"}
                          </td>
                        ) : null}
                        {key === "tags" ? (
                          <td style={{ fontSize: 11.5 }}>
                            {(r.event_parameters || []).length === 0 ? (
                              <span style={{ color: "var(--ink-4)" }}>—</span>
                            ) : (
                              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                {(r.event_parameters || []).map((p, pi) => (
                                  <span key={pi} className="mono" style={{ fontSize: 11 }}>
                                    <span style={{ color: "var(--ink-3)" }}>{p.key}</span>
                                    <span style={{ color: "var(--ink-4)" }}> → </span>
                                    <span style={{ color: "var(--accent-ink)" }}>{p.value}</span>
                                  </span>
                                ))}
                              </div>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="field">
            <label>피드백 (거부 시)</label>
            <textarea className="textarea" value={feedback} onChange={e => setFeedback(e.target.value)}
              placeholder="예: add_to_wishlist는 클릭 트리거로 바꿔주세요..." />
          </div>

          <div className="plan-action">
            <div className="muted-mono">승인 시 Node 6 GTM Creation으로 진행</div>
            <div className="row tight">
              <button className="btn ghost" disabled={submitting} onClick={() => sendHitl(false)}>
                피드백 후 재설계
              </button>
              <button className="btn approve" disabled={submitting} onClick={() => sendHitl(true)}>
                <Icon name="check" size={12} className="btn-ico" /> 승인하고 진행
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 4. History ──────────────────────────────────────────────────────────
function HistoryScreen({ onSelectRun }) {
  const items = window.useHistory();

  const statusChip = (s) => {
    const map = {
      running:      { cls: "accent", text: "running" },
      done:         { cls: "",       text: "완료" },
      failed:       { cls: "danger", text: "실패" },
      hitl_wait:    { cls: "warn",   text: "HITL 대기" },
    };
    const m = map[s] || { cls: "", text: s };
    return <span className={`chip ${m.cls}`}>{m.text}</span>;
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Run 히스토리</h1>
          <div className="page-sub">logs/{"{run_id}"}/report.md · {items.length}개 Run</div>
        </div>
      </div>

      <div className="history">
        <div className="history-row head">
          <div>time</div><div>target</div><div>page × tag</div><div>events</div><div>status</div><div>duration</div>
        </div>
        {items.length === 0 ? (
          <div style={{ padding: "24px 20px", color: "var(--ink-3)" }}>실행 내역이 없습니다.</div>
        ) : items.map((h, i) => (
          <div key={i} className="history-row" style={{ cursor: "pointer" }}
               onClick={() => onSelectRun && onSelectRun(h.run_id)}>
            <div className="tstamp">{h.t ? h.t.slice(0, 16) : "—"}</div>
            <div>
              <div className="urlcell">{h.url}</div>
              <div className="meta mono" style={{ fontSize: 11.5 }}>{h.run_id}</div>
            </div>
            <div className="mono" style={{ fontSize: 12.5 }}>{h.pageType || "—"} · {h.tagType || "—"}</div>
            <div className="mono">{h.events || 0}</div>
            <div>{statusChip(h.status)}</div>
            <div className="mono" style={{ color: "var(--ink-3)", fontSize: 12 }}>{h.dur || "—"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 5. GTM Resources result ─────────────────────────────────────────────
function ResourcesScreen({ runId }) {
  const { state, publishResult } = window.useRunLog(runId);
  const createdVars = state.created_variables || [];
  const createdTrigs = state.created_triggers || [];
  const createdTags = state.created_tags || [];
  const wsId = state.workspace_id || "—";
  const isRunning = state.status === "running";

  if (!runId) {
    return (
      <div className="page">
        <div className="page-header">
          <div><h1 className="page-title">생성된 GTM 리소스</h1>
            <div className="page-sub">실행 중인 Run이 없습니다.</div></div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">생성된 GTM 리소스</h1>
          <div className="page-sub">Workspace {wsId} · {runId}</div>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat"><div className="label">Variables</div>
          <div className="value">{createdVars.length}<span className="delta">{isRunning ? "생성 중" : "완료"}</span></div></div>
        <div className="stat"><div className="label">Triggers</div>
          <div className="value">{createdTrigs.length}</div></div>
        <div className="stat"><div className="label">Tags</div>
          <div className="value">{createdTags.length}</div></div>
        <div className="stat"><div className="label">Status</div>
          <div className="value mono" style={{ fontSize: 15 }}>{state.status || "—"}</div></div>
      </div>

      <div className="res-grid">
        {[
          { title: "Variables", list: createdVars },
          { title: "Triggers",  list: createdTrigs },
          { title: "Tags",      list: createdTags },
        ].map(col => (
          <div className="res-col" key={col.title}>
            <div className="res-head">
              <h4>{col.title}</h4>
              <span className="muted-mono">{col.list.length}</span>
            </div>
            <div className="res-list">
              {col.list.map((r, i) => (
                <div key={i} className="res-item">
                  <span className="name">{r.name}</span>
                  <span className="status" style={{ color: "var(--accent-ink)" }}>+ new</span>
                </div>
              ))}
              {col.list.length === 0 ? (
                <div style={{ padding: "8px 12px", color: "var(--ink-3)" }}>
                  {isRunning ? "생성 대기 중..." : "없음"}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {publishResult ? (
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title">Publish 결과</div>
          </div>
          <div className="panel-body">
            {publishResult.success ? (
              <div className="row tight">
                <span className="chip accent">✓ Publish 완료</span>
                <span className="mono">Version {publishResult.version_id}</span>
              </div>
            ) : (
              <div className="row tight" style={{ alignItems: "flex-start" }}>
                <span className="chip warn" style={{ marginTop: 2 }}>Publish 경고</span>
                <div style={{ flex: 1 }}>{publishResult.warning}</div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── 6. Report view ──────────────────────────────────────────────────────
function ReportScreen({ runId }) {
  const md = window.useReport(runId);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Report · {runId || "—"}</h1>
          <div className="page-sub mono">logs/{runId || "?"}/report.md</div>
        </div>
        <div className="row tight">
          {md ? (
            <button className="btn" onClick={() => {
              navigator.clipboard.writeText(md).catch(() => {});
            }}>
              <Icon name="copy" size={12} className="btn-ico" />MD 복사
            </button>
          ) : null}
        </div>
      </div>

      <div className="report-grid">
        <Markdown source={md || (runId ? "보고서 로딩 중... (에이전트 완료 후 생성됩니다)" : "Run ID가 없습니다.")} />
      </div>
    </div>
  );
}

// ── 7. Workspace Management ─────────────────────────────────────────────
const EMPTY_FORM = { name: "", accountId: "", containerId: "", gtmWorkspaceId: "", defaultUrl: "" };

function WsField({ label, field, placeholder, mono, form, setForm }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input
        className={`input${mono ? " mono" : ""}`}
        placeholder={placeholder}
        value={form[field]}
        onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
      />
    </div>
  );
}

function WorkspaceScreen() {
  const { workspaces, activeId, add, update, remove, setActive } = window.useWorkspaces();
  const [editId, setEditId] = useState(null);   // 편집 중인 workspace id ("new" = 신규 추가)
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");

  const openNew = () => { setForm(EMPTY_FORM); setEditId("new"); setError(""); };
  const openEdit = (ws) => { setForm({ ...EMPTY_FORM, ...ws }); setEditId(ws.id); setError(""); };
  const cancelEdit = () => { setEditId(null); setError(""); };

  const saveForm = () => {
    if (!form.name.trim() || !form.accountId.trim() || !form.containerId.trim()) {
      setError("이름, Account ID, Container ID는 필수입니다.");
      return;
    }
    if (editId === "new") {
      const id = add(form);
      setActive(id);
    } else {
      update(editId, form);
    }
    setEditId(null);
    setError("");
  };

  const handleActivate = (id) => {
    setActive(id);
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Workspaces</h1>
          <div className="page-sub">GTM 컨테이너 구성을 저장하고 Run 시 자동 적용합니다.</div>
        </div>
        <button className="btn primary" onClick={openNew}>
          <Icon name="plus" size={12} className="btn-ico" />워크스페이스 추가
        </button>
      </div>

      {/* 신규 추가 폼 */}
      {editId === "new" ? (
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><Icon name="plus" size={14} />새 워크스페이스</div>
          </div>
          <div className="panel-body" style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <WsField label="이름" field="name" placeholder="예: Lee Korea (prod)" form={form} setForm={setForm} />
              <WsField label="기본 URL" field="defaultUrl" placeholder="https://shop.example.com" mono form={form} setForm={setForm} />
              <WsField label="GTM Account ID" field="accountId" placeholder="6123847219" mono form={form} setForm={setForm} />
              <WsField label="GTM Container ID" field="containerId" placeholder="GTM-XXXXXXX" mono form={form} setForm={setForm} />
              <WsField label="GTM Workspace ID (선택)" field="gtmWorkspaceId" placeholder="비워두면 자동 생성" mono form={form} setForm={setForm} />
            </div>
            {error ? <div style={{ color: "var(--danger)", fontSize: 12.5 }}>{error}</div> : null}
            <div className="row tight" style={{ justifyContent: "flex-end" }}>
              <button className="btn ghost" onClick={cancelEdit}>취소</button>
              <button className="btn primary" onClick={saveForm}>저장 및 활성화</button>
            </div>
          </div>
        </div>
      ) : null}

      {/* 워크스페이스 카드 목록 */}
      {workspaces.length === 0 && editId !== "new" ? (
        <div className="panel">
          <div className="panel-body" style={{ padding: "32px 20px", textAlign: "center", color: "var(--ink-3)" }}>
            저장된 워크스페이스가 없습니다.&nbsp;
            <span style={{ cursor: "pointer", color: "var(--accent-ink)" }} onClick={openNew}>추가하기</span>
          </div>
        </div>
      ) : null}

      <div className="ws-grid">
        {workspaces.map(ws => {
          const isActive = ws.id === activeId;
          const isEditing = editId === ws.id;
          return (
            <div key={ws.id} className={`ws-card${isActive ? " active" : ""}`}>
              <div className="ws-card-head">
                <div className="row tight" style={{ flex: 1, minWidth: 0 }}>
                  {isActive ? <span className="chip accent"><span className="mini-dot" />활성</span> : null}
                  <span className="ws-name">{ws.name || "이름 없음"}</span>
                </div>
                <div className="row tight">
                  {!isActive ? (
                    <button className="btn ghost sm" onClick={() => handleActivate(ws.id)}>활성화</button>
                  ) : null}
                  <button className="btn ghost sm" onClick={() => isEditing ? cancelEdit() : openEdit(ws)}>
                    {isEditing ? "취소" : "편집"}
                  </button>
                  <button className="btn ghost sm danger-hover" onClick={() => remove(ws.id)}>
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              </div>

              {isEditing ? (
                <div style={{ display: "grid", gap: 12, padding: "0 0 4px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <WsField label="이름" field="name" placeholder="예: Lee Korea (prod)" form={form} setForm={setForm} />
                    <WsField label="기본 URL" field="defaultUrl" placeholder="https://shop.example.com" mono form={form} setForm={setForm} />
                    <WsField label="GTM Account ID" field="accountId" placeholder="6123847219" mono form={form} setForm={setForm} />
                    <WsField label="GTM Container ID" field="containerId" placeholder="GTM-XXXXXXX" mono form={form} setForm={setForm} />
                    <WsField label="GTM Workspace ID (선택)" field="gtmWorkspaceId" placeholder="비워두면 자동 생성" mono form={form} setForm={setForm} />
                  </div>
                  {error ? <div style={{ color: "var(--danger)", fontSize: 12.5 }}>{error}</div> : null}
                  <div className="row tight" style={{ justifyContent: "flex-end" }}>
                    <button className="btn primary sm" onClick={saveForm}>저장</button>
                  </div>
                </div>
              ) : (
                <div className="ws-meta">
                  <span className="chip mono">{ws.accountId || "—"}</span>
                  <span className="chip mono">{ws.containerId || "—"}</span>
                  {ws.defaultUrl ? (
                    <span className="muted-mono" style={{ fontSize: 12, color: "var(--ink-3)" }}>{ws.defaultUrl}</span>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {workspaces.length > 0 ? (
        <div className="muted-mono" style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 4 }}>
          활성화된 워크스페이스의 GTM 정보는 새 Run 시작 시 폼에 자동 반영됩니다.
        </div>
      ) : null}
    </div>
  );
}

Object.assign(window, {
  RunStartScreen, RunLiveScreen, HitlScreen, HistoryScreen, ResourcesScreen, ReportScreen, WorkspaceScreen,
});
