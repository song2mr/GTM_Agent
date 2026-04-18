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

1. 현재 페이지 스냅샷(HTML 축약) + `EVENT_CAPTURE_GUIDE` 목표 가이드 + 세션 전체 액션 히스토리 → LLM에 전달
2. LLM이 히스토리를 보고 현재 단계를 파악한 뒤 다음 액션 결정
3. `browser/actions.py`로 실행 → `ActionResult` 수신
4. 결과(성공/실패/이벤트 발화 여부)를 `_action_history`에 누적
5. `MAX_STEPS` 소진 시 해당 이벤트를 `manual_required`로 이관

### 스텝 정책

- `MAX_STEPS = 8` — 재시도가 아닌 멀티스텝 탐색 한도
- 액션 성공 but 이벤트 미발화 → "선행 조건이 있다는 신호"로 LLM에 전달, 다음 스텝 진행
- 액션 실패 → 에러 메시지를 히스토리에 기록, LLM이 다른 selector 시도

### 액션 히스토리 (`_action_history`)

`LLMNavigator` 인스턴스에 세션 전체에 걸쳐 누적된다. 이벤트 간 리셋 없음.

```python
# 항목 구조 — HTML 없음, 메타데이터만 포함
{
    "step": int,
    "target_event": str,   # 어느 이벤트를 캡처하던 중이었는지
    "action": str,
    "selector": str,
    "url": str,
    "error": str,
    "event_fired": bool,
}
```

LLM이 받는 히스토리 텍스트 예시:
```
스텝1 [view_item] navigate (https://shop.com/product/1) → 이벤트 발화됨
스텝1 click (.size-option-M) → 성공 but 이벤트 미발화
스텝2 click (.btn-add-cart) → 이벤트 발화됨
```
현재 이벤트 액션은 라벨 없음, 이전 이벤트 액션은 `[이벤트명]` 라벨로 구분.

### EVENT_CAPTURE_GUIDE

이벤트별 **목표** 가이드를 담는 딕셔너리. "무엇을 클릭하라"가 아니라 "어떤 조건이 충족되어야 이벤트가 발화되는가"를 서술한다.

```python
EVENT_CAPTURE_GUIDE = {
    "view_item":       "목표: PDP 진입 시 자동 발화. 현재 홈/PLP이면 상품 클릭 → PDP 이동",
    "add_to_cart":     "목표: 장바구니 버튼 클릭 후 발화. 필수 옵션 미선택 시 먼저 선택",
    "add_to_wishlist": "목표: 찜 버튼 클릭 후 발화. PDP 또는 PLP 카드에 존재",
    "view_item_list":  "목표: PLP 진입 시 자동 발화. 카테고리 링크로 navigate",
    ...
}
```

새 이벤트 지원 시 이 딕셔너리에만 항목 추가하면 된다.

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
