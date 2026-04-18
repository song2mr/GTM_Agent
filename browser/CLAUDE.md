# browser CLAUDE.md

Playwright 기반 브라우저 자동화 레이어.
모든 페이지 조작은 이 패키지를 통해서만 수행한다.

---

## 파일 구성

| 파일 | 역할 |
|------|------|
| `listener.py` | dataLayer Persistent Event Listener 주입·조회·진단 |
| `navigator.py` | LLM Navigator 루프 (이벤트별 탐색 전략) |
| `cart_addition_navigator.py` | 장바구니 담기 전용 Navigator (스텝 상한 `config/exploration_limits.yaml`, 채팅 모델 `config/llm_models.yaml`의 `cart_addition_navigator`) |
| `begin_checkout_navigator.py` | 결제 시작 전용 Navigator (스텝 상한 동일, 모델 키 `begin_checkout_navigator`) |
| `actions.py` | click / navigate / scroll / form_fill / **select_option** / **set_location_hash** 래퍼 |

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
  { data: { event: "view_item", ecommerce: {...} }, timestamp: 1712345678901, url: "https://..." },
  ...
]
```

원본 `dataLayer.push` 인자를 `data`로 감싸고 `timestamp`·`url` 메타를 덧붙여 누적한다. GTM 내부 이벤트(`gtm.js`, `gtm.dom`, `gtm.load`)도 포함.

### 주요 함수

```python
inject_listener(page)                # listener 주입
get_captured_events(page) -> list    # window.__gtm_captured 반환
event_fingerprint(ev) -> tuple       # (timestamp, event명, url) — 중복 판정 키
diagnose_datalayer(page) -> dict     # {"status": "full"|"partial"|"none", ...}
```

### 중복 판정 규칙

Navigator / Explorer에서 `captured_so_far`에 대한 `in` 비교는 금지.
`event_fingerprint(e)`로 얻은 튜플을 `set`에 넣어 O(1) 판정한다. dict 동등성 비교는 메타 필드가 추가되면 같은 이벤트를 "다른 것"으로 오인할 수 있다.

---

## navigator.py

### LLM Navigator 루프

1. 현재 페이지 스냅샷(HTML 축약) + `EVENT_CAPTURE_GUIDE` 목표 가이드 + 세션 전체 액션 히스토리 → LLM에 전달
2. LLM이 히스토리를 보고 현재 단계를 파악한 뒤 다음 액션 결정
3. `browser/actions.py`로 실행 → `ActionResult` 수신
4. 결과(성공/실패/이벤트 발화 여부)를 `_action_history`에 누적
5. `MAX_STEPS` 소진 시 해당 이벤트를 `manual_required`로 이관

`run_for_event`에서 액션 성공 후 이벤트가 아직 없을 때도 히스토리는 **`self._action_history.append`** 로만 누적해야 한다(잘못된 변수명은 `NameError`로 에이전트 스레드가 종료되어 UI가 무한 대기처럼 보일 수 있음).

`close_popup`은 **이 `run_for_event` 호출당 1회**(루프 진입 전)만 호출한다. 매 스텝마다 동일 닫기 셀렉터를 연타하지 않는다. 추가 레이어는 LLM의 `click`으로 처리.

**이벤트 전략 범주** (`navigator.py`): `view_item_list`·`view_cart`는 **implicit**(진입형), `add_to_cart`·`add_to_wishlist`·`select_item`·`begin_checkout`은 **interaction**(클릭 필수), 그 외는 **hybrid**. 시스템/사용자 메시지 상단 배너로 LLM이 범주를 섞지 않도록 한다.

`ChatOpenAI(..., timeout=...)` 로 LLM 호출 상한을 두고, 호출 직전 `emit("thought", …)` 로 UI에 진행 중임을 알린다.

**관측 로그(`run.log`)**: `decide_next_action`마다 URL·스텝·스냅샷 길이·비정상 스냅샷(타임아웃 문자열 등), LLM `ainvoke` 전후 경과 시간, 파싱된 `action`, `_execute_action` 성공 여부를 `logger.info`로 남긴다.

### 스텝 정책

- `MAX_STEPS`는 `config/exploration_limits.yaml`의 `navigator.max_llm_steps`에서 로드(기본 6). Cart/Begin Checkout Navigator와 동일 방식으로 튜닝한다.
- 채팅 모델 ID는 `config/llm_models.yaml`의 `navigator` / `cart_addition_navigator` / `begin_checkout_navigator` 구역을 쓴다(`llm_model(...)`). 생성자에 `model=`을 주면 YAML을 덮어쓴다.
- 재시도가 아닌 멀티스텝 탐색 한도
- 액션 성공 but 이벤트 미발화 → "선행 조건이 있다는 신호"로 LLM에 전달, 다음 스텝 진행
- 액션 실패 → 에러 메시지를 히스토리에 기록, LLM이 다른 selector 시도

### LLM 호출 에러 처리

- `LLMNavigator.__init__`에서 `utils.llm_json.make_chat_llm(...)` 팩토리로 **인스턴스 생성 시점에** ChatOpenAI를 만든다. 모듈 임포트 타이밍에 OPENAI_API_KEY를 요구하지 않는다.
- `decide_next_action` 내부의 `ainvoke`는 `try/except`로 감싸 네트워크·rate limit·타임아웃을 `{"action": "impossible", ...}` 결정으로 변환한다. 파이프라인은 죽지 않고 Manual 이관으로 넘어간다.
- JSON 파싱은 `utils.llm_json.parse_llm_json`만 사용한다. `split("```")[1]` 같은 직접 파싱은 펜스가 하나일 때 IndexError를 내므로 금지.

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
select_option(page, selector, value, timeout=8000) -> ActionResult
set_location_hash(page, fragment) -> ActionResult
close_popup(page) -> ActionResult
get_page_snapshot(page, max_chars=…, *, prefer_bottom=False) -> str   # HTML 축약
```

`get_page_snapshot`은 `asyncio.wait_for(page.content(), 30.0)` 으로 **원본 HTML 수집 상한(30초)**. `prefer_bottom=True`이면 긴 문서에서 **앞·뒤(하단 근처)** 를 합쳐 interaction 이벤트용으로 본문이 잘리지 않게 한다. `run.log`에 `[Snapshot] …` 단계가 기록된다.

`navigate()`는 `page.goto`에 더해 `asyncio.wait_for`를 **failsafe**로 둔다. 내부 PW 타임아웃(`timeout` ms)이 정상 동작하면 이쪽이 먼저 발동하고, 드물게 `page.goto`가 내부 타임아웃을 넘겨도 끝나지 않는 병리적 경우에만 외부 상한(PW 타임아웃 + 5초, 최소 25초)이 작동한다. `run.log`에 두 상한 모두 기록된다.

`close_popup()`은 **매 이벤트 루프 시작 시 1회만** 호출한다. 내부에서 selector 목록을 돌면서 `query_selector`로 존재 여부만 먼저 확인하고, **보이는 요소가 있을 때만** 짧은 타임아웃(800ms)으로 click한다. 팝업 없는 페이지에서 10초씩 낭비하지 않게 한 것이다.

### 타임아웃 정책

| 액션 | 기본 타임아웃 |
|------|------------|
| click | 5,000ms |
| navigate | 15,000ms |
| form_fill | 5,000ms |

`wait_until="domcontentloaded"` 사용 — `networkidle` 대기는 SPA에서 무한 대기 위험.
