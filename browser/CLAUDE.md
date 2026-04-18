# browser CLAUDE.md

Playwright 기반 브라우저 자동화 레이어.
모든 페이지 조작은 이 패키지를 통해서만 수행한다.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `listener.py` | dataLayer Persistent Event Listener 주입·조회·진단 |
| `navigator.py` | LLM Navigator 루프 (이벤트별 탐색 전략) |
| `actions.py` | click / navigate / scroll / form_fill 액션 래퍼 |

---

## listener.py

### Persistent Listener 원칙

`page.add_init_script()`로 주입 → SPA 페이지 이동 후에도 listener가 유지된다.
`page.evaluate()`로 주입하면 이동 시 사라지므로 절대 사용 금지.

```python
await inject_listener(page)   # 반드시 goto() 전에 호출
```

### `window.__gtm_captured` 구조

```js
window.__gtm_captured = [
  { event: "page_view", url: "/", ts: 1234567890, ... },
  { event: "view_item", ecommerce: { ... } },
]
```

원본 `dataLayer.push` 인자를 그대로 누적한다. GTM 내부 이벤트(`gtm.js`, `gtm.dom`, `gtm.load`)도 포함.

### 주요 함수

```python
inject_listener(page)                # listener 주입
get_captured_events(page) -> list    # window.__gtm_captured 반환
diagnose_datalayer(page) -> str      # "full" | "partial" | "none"
```

---

## navigator.py

### LLM Navigator 루프

1. 현재 페이지 스냅샷(HTML 축약) + `EVENT_CAPTURE_GUIDE` 힌트 → LLM에 전달
2. LLM이 다음 액션(`click` / `navigate` / `scroll` / `form_fill`) 반환
3. `browser/actions.py`로 실행 → `ActionResult` 수신
4. 실패 시 카운터 증가 → 3회 초과 시 해당 이벤트를 `manual_required`로 이관

### EVENT_CAPTURE_GUIDE

이벤트별 탐색 힌트를 담는 딕셔너리. Navigator 프롬프트에 자동 주입된다.

```python
EVENT_CAPTURE_GUIDE = {
    "view_item":       "홈/PLP이면 상품 클릭 → PDP 이동 먼저",
    "add_to_cart":     "PDP의 '장바구니/담기' 버튼",
    "add_to_wishlist": "♡/찜/하트/관심상품 버튼 — PLP 카드 위 또는 PDP에 존재",
    "view_item_list":  "카테고리/목록 링크 클릭",
    ...
}
```

새 이벤트 지원 시 이 딕셔너리에만 항목 추가하면 된다.

### 재시도 정책

- 클릭 실패: 최대 3회 재시도
- selector 변경: LLM이 alternative selector 제안
- 3회 모두 실패: `manual_required`에 추가, 루프 계속

---

## actions.py

모든 액션은 예외를 던지지 않고 `ActionResult`를 반환한다.
Navigator가 실패 메시지를 LLM에게 다시 전달해 대응할 수 있게 한다.

```python
@dataclass
class ActionResult:
    success: bool
    message: str = ""
    error: str = ""
```

### 주요 함수

```python
click(page, selector, timeout=5000) -> ActionResult
navigate(page, url, timeout=15000) -> ActionResult
scroll(page, direction="down", px=500) -> ActionResult
form_fill(page, selector, value) -> ActionResult
get_page_snapshot(page, max_chars=8000) -> str   # HTML 축약 스냅샷
```

### 타임아웃 정책

| 액션 | 기본 타임아웃 |
|------|------------|
| click | 5,000ms |
| navigate | 15,000ms |
| form_fill | 5,000ms |

`wait_until="domcontentloaded"` 사용 — `networkidle` 대기는 SPA에서 무한 대기 위험.
