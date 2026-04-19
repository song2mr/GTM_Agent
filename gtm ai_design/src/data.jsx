/* global window */

// Mock data for a realistic-looking run.
const RUN = {
  id: "20260418_092214",
  startedAt: "2026-04-18 09:22:14",
  targetUrl: "https://shop.leekorea.co.kr",
  userRequest: "GA4 이커머스 이벤트 전체 설정 (view_item_list, view_item, add_to_cart, add_to_wishlist, view_cart, begin_checkout) — Measurement ID: G-KX82JQ4M1P",
  tagType: "GA4",
  accountId: "6123847219",
  containerId: "GTM-NV7P3MK",
  workspaceId: "ws-20260418-0922",
  measurementId: "G-KX82JQ4M1P",
  pageType: "PLP",
  duration: "4m 12s",
};

const NODES = [
  { id: 1,   key: "page_classifier",    title: "Page Classifier",     sub: "페이지 로드 · Listener 주입 · 타입 판단", status: "done",   duration: "8.2s",  tokens: "12.4k" },
  { id: 1.5, key: "structure_analyzer", title: "Structure Analyzer",  sub: "DOM / JSON-LD 구조 추출",              status: "done",   duration: "4.1s",  tokens: "3.2k"  },
  { id: 2,   key: "journey_planner",    title: "Journey Planner",     sub: "탐색 큐 생성 · 자동/수동 분류",         status: "done",   duration: "2.9s",  tokens: "2.8k"  },
  { id: 3,   key: "active_explorer",    title: "Active Explorer",     sub: "LLM Navigator × Playwright 루프",      status: "run",    duration: "1m 42s", tokens: "48.1k" },
  { id: 4,   key: "manual_capture",     title: "Manual Capture",      sub: "purchase / refund 게이트웨이",          status: "queued", duration: "—",     tokens: "—"     },
  { id: 5,   key: "planning",           title: "Planning · HITL",     sub: "GTM 설계안 · 사용자 승인",              status: "queued", duration: "—",     tokens: "—"     },
  { id: 6,   key: "gtm_creation",       title: "GTM Creation",        sub: "Variable → Trigger → Tag",             status: "queued", duration: "—",     tokens: "—"     },
  { id: 7,   key: "publish",            title: "Publish",             sub: "Version 생성 · 컨테이너 게시",          status: "queued", duration: "—",     tokens: "—"     },
  { id: 8,   key: "reporter",           title: "Reporter",            sub: "report.md 작성",                        status: "queued", duration: "—",     tokens: "—"     },
];

const CAPTURED_EVENTS = [
  { t: "09:22:24.812", event: "page_view",       url: "/",               source: "dataLayer", status: "ok",  params: { page_type: "home", currency: "KRW" } },
  { t: "09:22:31.104", event: "view_item_list",  url: "/category/best",  source: "dataLayer", status: "ok",  params: { item_list_id: "best", items: 24 } },
  { t: "09:22:38.421", event: "view_item",       url: "/product/3481",   source: "dataLayer", status: "ok",  params: { item_id: "3481", price: 29000 } },
  { t: "09:22:41.774", event: "add_to_wishlist", url: "/product/3481",   source: "dataLayer", status: "ok",  params: { item_id: "3481", value: 29000 } },
  { t: "09:22:47.233", event: "add_to_cart",     url: "/product/3481",   source: "dataLayer", status: "ok",  params: { item_id: "3481", quantity: 1 } },
  { t: "09:22:53.011", event: "view_cart",       url: "/cart",           source: "dataLayer", status: "ok",  params: { value: 29000, items: 1 } },
  { t: "09:22:59.802", event: "begin_checkout",  url: "/checkout",       source: "dataLayer", status: "new", params: { value: 29000, currency: "KRW" } },
];

const THOUGHTS = [
  { who: "agent", label: "Planner", time: "09:22:14", kind: "plain",
    text: "요청 파싱 중. 타겟은 PLP처럼 보이고, user_request에 6개 표준 이벤트 + 커스텀 add_to_wishlist가 명시됨. Measurement ID G-KX82JQ4M1P 감지." },
  { who: "tool",  label: "playwright.navigate", time: "09:22:15", kind: "tool",
    text: "GET https://shop.leekorea.co.kr → 200 · networkidle 대기" },
  { who: "agent", label: "PageClassifier", time: "09:22:23", kind: "plain",
    text: "dataLayer 확인: window.__gtm_captured[0..1] = [{event:'gtm.js'}, {event:'page_view'}]. → datalayer_status = 'full'. 추출 방식: datalayer." },
  { who: "agent", label: "JourneyPlanner", time: "09:22:29", kind: "plain",
    text: "탐색 큐 구성: view_item_list → view_item → add_to_wishlist → add_to_cart → view_cart → begin_checkout → purchase. purchase는 Manual Capture로 분리." },
  { who: "tool",  label: "playwright.click", time: "09:22:32", kind: "tool",
    text: "a[href='/category/best'] · 결과: 네비게이션 발생 · dataLayer push: view_item_list" },
  { who: "agent", label: "Navigator", time: "09:22:38", kind: "highlight",
    text: "PLP에서 1번째 상품 카드(.product-card__link:nth-child(1)) 클릭 시도. 가격 표기(‘29,000원’) 파싱 완료 → price 29000 검증 예상." },
  { who: "tool",  label: "playwright.click", time: "09:22:41", kind: "tool",
    text: "button[aria-label='찜하기'] · dataLayer push 감지됨 ✓" },
  { who: "agent", label: "Navigator", time: "09:22:46", kind: "plain",
    text: "장바구니 담기 버튼을 시도합니다. 상품 옵션 모달 감지 → 기본값 선택 후 재시도." },
];

const PLAN = {
  variables: [
    { kind: "new",    name: "DLV - event",         type: "Data Layer Variable",  source: "event" },
    { kind: "new",    name: "DLV - ecommerce.currency", type: "Data Layer Variable", source: "ecommerce.currency" },
    { kind: "new",    name: "DLV - ecommerce.value",    type: "Data Layer Variable", source: "ecommerce.value" },
    { kind: "new",    name: "DLV - ecommerce.items",    type: "Data Layer Variable", source: "ecommerce.items" },
    { kind: "new",    name: "DLV - item_id",       type: "Data Layer Variable",  source: "item_id" },
    { kind: "new",    name: "Const - GA4 MID",     type: "Constant",             source: "G-KX82JQ4M1P" },
  ],
  triggers: [
    { kind: "new", name: "CE - view_item_list",   type: "Custom Event", filter: "{{_event}} equals view_item_list" },
    { kind: "new", name: "CE - view_item",        type: "Custom Event", filter: "{{_event}} equals view_item" },
    { kind: "new", name: "CE - add_to_wishlist",  type: "Custom Event", filter: "{{_event}} equals add_to_wishlist" },
    { kind: "new", name: "CE - add_to_cart",      type: "Custom Event", filter: "{{_event}} equals add_to_cart" },
    { kind: "new", name: "CE - view_cart",        type: "Custom Event", filter: "{{_event}} equals view_cart" },
    { kind: "new", name: "CE - begin_checkout",   type: "Custom Event", filter: "{{_event}} equals begin_checkout" },
  ],
  tags: [
    { kind: "update", name: "GA4 - Config",         type: "Google Tag (GA4)",            trigger: "All Pages",      note: "MID 덮어쓰기" },
    { kind: "new",    name: "GA4 - view_item_list", type: "Google Analytics: GA4 Event", trigger: "CE - view_item_list" },
    { kind: "new",    name: "GA4 - view_item",      type: "Google Analytics: GA4 Event", trigger: "CE - view_item" },
    { kind: "new",    name: "GA4 - add_to_wishlist",type: "Google Analytics: GA4 Event", trigger: "CE - add_to_wishlist" },
    { kind: "new",    name: "GA4 - add_to_cart",    type: "Google Analytics: GA4 Event", trigger: "CE - add_to_cart" },
    { kind: "new",    name: "GA4 - view_cart",      type: "Google Analytics: GA4 Event", trigger: "CE - view_cart" },
    { kind: "new",    name: "GA4 - begin_checkout", type: "Google Analytics: GA4 Event", trigger: "CE - begin_checkout" },
  ],
};

const HISTORY = [
  { t: "2026-04-18 09:22", url: "shop.leekorea.co.kr",       pageType: "PLP",      tagType: "GA4",   events: 7, status: "running",   dur: "1m 42s" },
  { t: "2026-04-18 09:15", url: "shop.leekorea.co.kr",       pageType: "PLP",      tagType: "GA4",   events: 7, status: "publish_warn", dur: "4m 02s" },
  { t: "2026-04-18 01:18", url: "shop.leekorea.co.kr/cart",  pageType: "cart",     tagType: "GA4",   events: 5, status: "success",   dur: "3m 48s" },
  { t: "2026-04-18 00:10", url: "shop.leekorea.co.kr",       pageType: "home",     tagType: "GA4",   events: 6, status: "success",   dur: "3m 21s" },
  { t: "2026-04-17 23:51", url: "shop.leekorea.co.kr",       pageType: "PLP",      tagType: "kakao", events: 4, status: "failed",    dur: "1m 04s" },
  { t: "2026-04-17 23:36", url: "m.leekorea.co.kr",          pageType: "PDP",      tagType: "GA4",   events: 3, status: "hitl",      dur: "—" },
  { t: "2026-04-17 22:54", url: "shop.leekorea.co.kr",       pageType: "checkout", tagType: "GA4",   events: 8, status: "success",   dur: "5m 11s" },
  { t: "2026-04-17 00:22", url: "demo.myshop.test",          pageType: "unknown",  tagType: "naver", events: 2, status: "failed",    dur: "0m 48s" },
];

const REPORT_MD = `# Run Report — 20260418_092214

**타겟:** https://shop.leekorea.co.kr   •   **태그 유형:** GA4   •   **Measurement ID:** G-KX82JQ4M1P
**실행 시간:** 2026-04-18 09:22:14 ~ 09:26:26 (4m 12s)

## 1. 기본 정보
- 계정: 6123847219 · 컨테이너: GTM-NV7P3MK
- 신규 Workspace: \`ws-20260418-0922\`
- 페이지 타입: PLP (Product List Page)
- 총 토큰 사용량: 66,540 (Claude Opus 4 · Haiku 4.5)

## 2. dataLayer 분석
\`datalayer_status\` = **full** — \`extraction_method\` = \`datalayer\`.
로드타임 이벤트 2건 (\`gtm.js\`, \`page_view\`) + 탐색 중 캡처 6건.

| 이벤트 | 처리 방식 | 결과 | 비고 |
| --- | --- | --- | --- |
| page_view | datalayer | ✓ | 로드 즉시 |
| view_item_list | navigator_datalayer | ✓ | 카테고리 ‘베스트’ 진입 |
| view_item | navigator_datalayer | ✓ | 1번째 상품 클릭 |
| add_to_wishlist | click_trigger_datalayer | ✓ | PLP 카드 ♡ 버튼 |
| add_to_cart | navigator_datalayer | ✓ | 옵션 모달 자동 처리 |
| view_cart | navigator_datalayer | ✓ | 장바구니 페이지 이동 |
| begin_checkout | navigator_datalayer | ✓ | ‘주문하기’ 버튼 |
| purchase | — | skipped | Manual Capture Gateway, 사용자가 C 선택 |

## 3. 이벤트별 특이사항
- **add_to_cart**: 옵션 선택 모달이 자동으로 닫히지 않아 1회 재시도 후 성공.
- **begin_checkout**: ‘로그인 필요’ 인터셉트 감지 → 쿠키 세션 파일 사용하여 통과.

## 4. GTM 생성 결과
- Variables: 6개 신규 (\`DLV - event\`, \`DLV - ecommerce.*\`, \`Const - GA4 MID\` ...)
- Triggers: 6개 신규 (\`CE - *\`)
- Tags: 6개 신규 + 1개 Update(GA4 - Config)

## 5. Publish 결과
\`publish_warning\`: \`insufficientPermissions\` — 계정 Publish 권한 부족으로 자동 게시 실패.
GTM UI에서 수동 게시 필요: https://tagmanager.google.com/
`;

window.RUN = RUN;
window.NODES = NODES;
window.CAPTURED_EVENTS = CAPTURED_EVENTS;
window.THOUGHTS = THOUGHTS;
window.PLAN = PLAN;
window.HISTORY = HISTORY;
window.REPORT_MD = REPORT_MD;
