/* global React, Icon, Timeline, Thoughts, Json, Markdown */
const { useState, useEffect, useMemo } = React;

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

  const persistAndStart = () => {
    if (rememberCreds) {
      localStorage.setItem("gtm:config", JSON.stringify({
        url, req, tag, accountId, containerId, workspaceId, measurementId, rememberCreds,
      }));
    } else {
      localStorage.removeItem("gtm:config");
    }
    onStart && onStart({ url, req, tag, accountId, containerId, workspaceId, measurementId });
  };

  const canStart = url && req && accountId && containerId;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">새 Run 시작</h1>
          <div className="page-sub">자연어로 요청하세요. 에이전트가 페이지를 탐색해 GTM을 설계·생성합니다.</div>
        </div>
        <div className="row tight">
          <span className="chip"><Icon name="clock" size={12} /> 마지막 Run · 7분 전</span>
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
                <input className="input mono" placeholder="GTM-XXXXXXX"
                       value={containerId} onChange={e => setContainerId(e.target.value)} />
              </div>
              <div className="field">
                <label>GTM_WORKSPACE_ID (선택)</label>
                <input className="input mono" placeholder="비워두면 자동으로 신규 생성"
                       value={workspaceId} onChange={e => setWorkspaceId(e.target.value)} />
              </div>
              <div className="field">
                <label>GA4 MEASUREMENT ID (선택)</label>
                <input className="input mono" placeholder="G-XXXXXXXX"
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
              여기선 어떤 계정·컨테이너로 작업할지만 지정하면 됩니다.
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
              <span className="chip"><Icon name="zap" size={12} /> 평균 4m</span>
            </div>
            <div className="row tight">
              <button className="btn ghost">템플릿 불러오기</button>
              <button className="btn primary" onClick={persistAndStart}
                      disabled={!canStart}
                      style={{ opacity: canStart ? 1 : 0.5, cursor: canStart ? "pointer" : "not-allowed" }}>
                <Icon name="play" size={12} className="btn-ico" />
                에이전트 실행
                <kbd style={{ marginLeft: 6 }}>⌘↵</kbd>
              </button>
            </div>
          </div>
          {!canStart ? (
            <div className="muted-mono" style={{ color: "var(--warn)", fontSize: 11.5 }}>
              GTM_ACCOUNT_ID와 GTM_CONTAINER_ID는 필수입니다.
            </div>
          ) : null}
        </div>
      </div>

      <div className="stats-row">
        <div className="stat"><div className="label">오늘 Run</div><div className="value">7<span className="delta">+3 어제 대비</span></div></div>
        <div className="stat"><div className="label">성공률 (7일)</div><div className="value">84%<span className="delta">32/38 성공</span></div></div>
        <div className="stat"><div className="label">평균 이벤트 캡처</div><div className="value">6.2<span className="delta">DL + Nav</span></div></div>
        <div className="stat"><div className="label">대기 중 HITL</div><div className="value">1<span className="delta">15m 전부터</span></div></div>
      </div>
    </div>
  );
}

// ── 2. Live Agent Run view ──────────────────────────────────────────────
function RunLiveScreen({ variation }) {
  const [active, setActive] = useState(3);
  const [events, setEvents] = useState(window.CAPTURED_EVENTS.slice(0, 6));
  const [thoughtIdx, setThoughtIdx] = useState(6);

  useEffect(() => {
    const id = setInterval(() => {
      setEvents(cur => {
        if (cur.length >= window.CAPTURED_EVENTS.length) return cur;
        return window.CAPTURED_EVENTS.slice(0, cur.length + 1);
      });
      setThoughtIdx(i => Math.min(i + 1, window.THOUGHTS.length));
    }, 4000);
    return () => clearInterval(id);
  }, []);

  const activeNode = window.NODES.find(n => n.id === active) || window.NODES[3];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Run · {window.RUN.id}</h1>
          <div className="page-sub mono">{window.RUN.targetUrl} · {window.RUN.pageType} · {window.RUN.tagType}</div>
        </div>
        <div className="row tight">
          <span className="token-usage"><span>in <b>48.2k</b></span><span>out <b>12.1k</b></span><span>$<b>0.18</b></span></span>
          <button className="btn"><Icon name="pause" size={12} className="btn-ico" />일시정지</button>
          <button className="btn danger">중지</button>
        </div>
      </div>

      <div className="run-grid">
        <Timeline nodes={window.NODES} activeId={active} onSelect={setActive} />

        <div className="detail">
          <div className="panel">
            <div className="panel-head">
              <div className="panel-title">
                <span className="chip accent"><span className="mini-dot" />Node {activeNode.id}</span>
                {activeNode.title}
              </div>
              <div className="panel-sub">{activeNode.sub}</div>
            </div>
            <div className="panel-body">
              <Thoughts items={window.THOUGHTS.slice(0, thoughtIdx)} typing={thoughtIdx >= window.THOUGHTS.length} />
            </div>
          </div>

          {variation === "B" ? (
            <div className="panel">
              <div className="panel-head">
                <div className="panel-title">Playwright 라이브 뷰</div>
                <div className="panel-sub">shop.leekorea.co.kr/category/best</div>
              </div>
              <div className="panel-body" style={{ padding: 14 }}>
                <div className="preview-frame">
                  <div className="preview-chrome">
                    <span className="bub" /><span className="bub" /><span className="bub" />
                    <span className="addr">
                      <span style={{ color: "var(--accent-ink)" }}>●</span>
                      shop.leekorea.co.kr/category/best
                    </span>
                  </div>
                  <div className="preview-viewport">
                    <div className="placeholder">[browser viewport placeholder · 1280×720]</div>
                    <div className="hit" style={{ top: 80, left: 120, width: 180, height: 80 }}>click target · .product-card:nth-child(1)</div>
                    <div className="hit" style={{ top: 200, left: 360, width: 44, height: 44, borderStyle: "solid" }}>♡</div>
                  </div>
                </div>
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
                        <td style={{ color: "var(--ink-2)" }}>{e.url}</td>
                        <td><span className="chip" style={{ padding: "1px 6px", fontSize: 10.5 }}>{e.source}</span></td>
                        <td style={{ color: "var(--ink-3)" }}>{JSON.stringify(e.params)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="panel-title">현재 계획 큐</div>
              <div className="panel-sub">Journey Planner</div>
            </div>
            <div className="panel-body">
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                <span className="chip accent"><Icon name="check" size={10} />view_item_list</span>
                <span className="chip accent"><Icon name="check" size={10} />view_item</span>
                <span className="chip accent"><Icon name="check" size={10} />add_to_wishlist</span>
                <span className="chip accent"><Icon name="check" size={10} />add_to_cart</span>
                <span className="chip" style={{ background: "var(--accent-soft)", borderColor: "var(--accent-line)", color: "var(--accent-ink)" }}>
                  <span className="mini-dot" />view_cart
                </span>
                <span className="chip">begin_checkout</span>
                <span className="chip warn">purchase · manual</span>
              </div>
              <div style={{ marginTop: 14 }}>
                <div className="spread"><span className="muted-mono">전체 진행률</span><span className="muted-mono">4/7</span></div>
                <div className="bar" style={{ marginTop: 6 }}><span style={{ width: "57%" }} /></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 3. HITL Approval ────────────────────────────────────────────────────
function HitlScreen({ onApprove }) {
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Plan 검토 · HITL</h1>
          <div className="page-sub">GTM에 반영하기 전, AI가 생성한 설계안을 확인하세요.</div>
        </div>
        <div className="row tight">
          <span className="chip warn"><Icon name="clock" size={12} />대기 중 · 15m 12s</span>
        </div>
      </div>

      <div className="hitl">
        <div className="hitl-head">
          <span className="stamp">Node 5 · Planning</span>
          <h3>GA4 이커머스 설계안</h3>
          <span style={{ marginLeft: "auto" }} className="muted-mono">ws-20260418 · GTM-NV7P3MK</span>
        </div>
        <div className="hitl-body">
          <div className="kv-grid">
            <dt>Target</dt><dd>shop.leekorea.co.kr · PLP</dd>
            <dt>Measurement ID</dt><dd className="mono">G-KX82JQ4M1P</dd>
            <dt>추출 방식</dt><dd>datalayer (full)</dd>
            <dt>이벤트 수</dt><dd>7 auto + 1 manual (purchase skipped)</dd>
          </div>

          {["variables", "triggers", "tags"].map((key) => (
            <div key={key} className="panel" style={{ boxShadow: "none" }}>
              <div className="panel-head">
                <div className="panel-title">
                  {key === "variables" ? "Variables" : key === "triggers" ? "Triggers" : "Tags"}
                  <span className="chip accent">+{window.PLAN[key].filter(x => x.kind === "new").length} new</span>
                  {window.PLAN[key].some(x => x.kind === "update")
                    ? <span className="chip info">↻ {window.PLAN[key].filter(x => x.kind === "update").length} update</span>
                    : null}
                </div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table className="plan-table">
                  <thead>
                    <tr>
                      <th style={{ width: 70 }}>kind</th>
                      <th>name</th>
                      <th>type</th>
                      <th>{key === "triggers" ? "filter" : key === "tags" ? "trigger" : "source"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {window.PLAN[key].map((r, i) => (
                      <tr key={i} className={r.kind}>
                        <td>
                          <span className={`chip ${r.kind === "new" ? "accent" : "info"}`} style={{ padding: "1px 6px" }}>
                            {r.kind === "new" ? "new" : "update"}
                          </span>
                        </td>
                        <td className="name">{r.name}</td>
                        <td style={{ color: "var(--ink-3)" }}>{r.type}</td>
                        <td className="mono" style={{ fontSize: 12 }}>{r.filter || r.trigger || r.source || r.note || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="field">
            <label>피드백 (n으로 거부 시)</label>
            <textarea className="textarea" placeholder="예: add_to_wishlist는 클릭 트리거로 바꿔주세요..."/>
          </div>

          <div className="plan-action">
            <div className="muted-mono">승인 시 Node 6 GTM Creation으로 진행</div>
            <div className="row tight">
              <button className="btn ghost">피드백 후 재설계 <kbd>n</kbd></button>
              <button className="btn approve" onClick={onApprove}>
                <Icon name="check" size={12} className="btn-ico" /> 승인하고 진행 <kbd style={{ marginLeft: 6, background: "rgba(255,255,255,.15)", borderColor: "rgba(255,255,255,.25)", color: "white" }}>y</kbd>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 4. History ──────────────────────────────────────────────────────────
function HistoryScreen() {
  const statusChip = (s) => {
    const map = {
      running:      { cls: "accent", text: "running" },
      success:      { cls: "",       text: "success" },
      failed:       { cls: "danger", text: "failed" },
      hitl:         { cls: "warn",   text: "awaiting HITL" },
      publish_warn: { cls: "warn",   text: "publish warn" },
    };
    const m = map[s] || { cls: "", text: s };
    return <span className={`chip ${m.cls}`}>{m.text}</span>;
  };
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Run 히스토리</h1>
          <div className="page-sub">logs/{"{run_id}"}/report.md · 128개 Run</div>
        </div>
        <div className="row tight">
          <div className="chip"><Icon name="search" size={12} />검색</div>
          <button className="btn"><Icon name="filter" size={12} className="btn-ico" />필터</button>
          <button className="btn primary"><Icon name="plus" size={12} className="btn-ico" />새 Run</button>
        </div>
      </div>

      <div className="history">
        <div className="history-row head">
          <div>time</div><div>target / request</div><div>page × tag</div><div>events</div><div>status</div><div>duration</div>
        </div>
        {window.HISTORY.map((h, i) => (
          <div key={i} className="history-row">
            <div className="tstamp">{h.t}</div>
            <div>
              <div className="urlcell">{h.url}</div>
              <div className="meta">GA4 이커머스 이벤트 전체 설정</div>
            </div>
            <div className="mono" style={{ fontSize: 12.5 }}>{h.pageType} · {h.tagType}</div>
            <div className="mono">{h.events}</div>
            <div>{statusChip(h.status)}</div>
            <div className="mono" style={{ color: "var(--ink-3)", fontSize: 12 }}>{h.dur}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 5. GTM Resources result ─────────────────────────────────────────────
function ResourcesScreen() {
  const status = (k) => k === "new" ? <span className="status" style={{ color: "var(--accent-ink)" }}>+ new</span>
    : <span className="status" style={{ color: "oklch(0.42 0.12 250)" }}>↻ updated</span>;
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">생성된 GTM 리소스</h1>
          <div className="page-sub">ws-20260418-0922 · Publish 대기 중</div>
        </div>
        <div className="row tight">
          <button className="btn"><Icon name="external" size={12} className="btn-ico" />GTM UI에서 열기</button>
          <button className="btn primary">
            <Icon name="zap" size={12} className="btn-ico" />게시 (Publish)
          </button>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat"><div className="label">Variables</div><div className="value">6<span className="delta">+6 new</span></div></div>
        <div className="stat"><div className="label">Triggers</div><div className="value">6<span className="delta">+6 new</span></div></div>
        <div className="stat"><div className="label">Tags</div><div className="value">7<span className="delta">+6 new · 1 updated</span></div></div>
        <div className="stat"><div className="label">Workspace</div><div className="value mono" style={{ fontSize: 15 }}>ws-0922<span className="delta">신규</span></div></div>
      </div>

      <div className="res-grid">
        {[
          { title: "Variables", list: window.PLAN.variables },
          { title: "Triggers",  list: window.PLAN.triggers },
          { title: "Tags",      list: window.PLAN.tags },
        ].map((col) => (
          <div className="res-col" key={col.title}>
            <div className="res-head">
              <h4>{col.title}</h4>
              <span className="muted-mono">{col.list.length}</span>
            </div>
            <div className="res-list">
              {col.list.map((r, i) => (
                <div key={i} className="res-item">
                  <span className="name">{r.name}</span>
                  {status(r.kind)}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="panel-title">Publish 경고</div>
          <div className="panel-sub">publish.py · Node 7</div>
        </div>
        <div className="panel-body">
          <div className="row tight" style={{ alignItems: "flex-start" }}>
            <span className="chip warn" style={{ marginTop: 2 }}>403 insufficientPermissions</span>
            <div style={{ flex: 1 }}>
              OAuth 스코프 문제가 아니라 GTM 계정의 Publish 권한이 부족합니다.
              GTM UI 관리 → 사용자 관리에서 Publish 권한을 부여하거나, 수동으로 게시해 주세요.
              <div className="muted-mono" style={{ marginTop: 6 }}>
                https://tagmanager.google.com/#/container/accounts/6123847219/containers/GTM-NV7P3MK
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6. Report view ──────────────────────────────────────────────────────
function ReportScreen() {
  const sections = ["기본 정보", "dataLayer 분석", "이벤트별 특이사항", "GTM 생성 결과", "Publish 결과"];
  const [active, setActive] = useState(0);
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Report · 20260418_092214</h1>
          <div className="page-sub mono">logs/20260418_092214/report.md · 4m 12s</div>
        </div>
        <div className="row tight">
          <button className="btn"><Icon name="copy" size={12} className="btn-ico" />MD 복사</button>
          <button className="btn"><Icon name="external" size={12} className="btn-ico" />파일 열기</button>
        </div>
      </div>

      <div className="report-grid">
        <div className="toc">
          <div className="muted-mono" style={{ padding: "4px 8px" }}>목차</div>
          {sections.map((s, i) => (
            <div key={i} className={`toc-item ${i === active ? "on" : ""}`} onClick={() => setActive(i)}>
              {i + 1}. {s}
            </div>
          ))}
          <div className="divider" />
          <div className="muted-mono" style={{ padding: "4px 8px" }}>토큰 사용량</div>
          <div style={{ padding: "4px 8px", display: "grid", gap: 2, fontSize: 11.5 }}>
            <div className="spread"><span className="dim">in</span><b className="mono">54.2k</b></div>
            <div className="spread"><span className="dim">out</span><b className="mono">12.3k</b></div>
            <div className="spread"><span className="dim">$ USD</span><b className="mono">0.31</b></div>
          </div>
        </div>
        <Markdown source={window.REPORT_MD} />
      </div>
    </div>
  );
}

Object.assign(window, {
  RunStartScreen, RunLiveScreen, HitlScreen, HistoryScreen, ResourcesScreen, ReportScreen,
});
