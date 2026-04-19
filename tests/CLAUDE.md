# tests CLAUDE.md

CanPlan 파이프라인의 **골든 회귀 테스트**. 프로젝트 전반은 pytest를 필수로 쓰지 않으므로,
각 파일은 모듈 실행(`py -3 tests/test_canplan_normalize.py`)만으로도 검증되도록 작성한다.

---

## 실행

```powershell
# 전체 (두 파일 순차 실행)
py -3 tests/test_canplan_normalize.py
py -3 tests/test_spec_builder.py

# pytest가 있으면 평소 사용대로 가능
pytest tests/ -q
```

각 파일 하단에 `_run()` 함수가 있고 `if __name__ == "__main__": _run()`로 직접 실행된다. 실패 시 `assert` 한 줄에서 멈추고 스택 트레이스를 낸다.

---

## 파일 구성

| 파일 | 대상 | 주요 커버리지 |
|------|------|---------------|
| `test_canplan_normalize.py` | `agent/canplan/normalize.py` + `evidence.py` | DL health 판정, 소스 폴백(`DL_HEALTH_IGNORED`), `in_set` 금지, CJS `TEMPLATE_UNKNOWN`, URL regex 네거티브 샘플, 로드타임 pageview 폴백 |
| `test_spec_builder.py` | `gtm/spec_builder.py` | CanPlan → GTM 모델 변환(페이지패스 regex 트리거, 클릭 트리거 + CJS 변수 포함) |

### test_canplan_normalize.py 케이스
- `test_dl_health_unhealthy_path_detected` — `ecommerce.items[0].item_id`·zero price·빈 currency가 `unhealthy`로 태깅되는지.
- `test_normalize_rejects_dl_health_ignored` — healthy DL 경로가 있는데 Plan이 DOM/JSON-LD를 고르면 `DL_HEALTH_IGNORED` 에러.
- `test_normalize_bans_in_set_op` — 트리거 필터의 `in_set` 연산자가 거부되는지.
- `test_normalize_rejects_unknown_cjs_template` — 미등록 CJS `template_id` → `TEMPLATE_UNKNOWN`.
- `test_negative_sample_url_not_matched_policy` — PLP seed regex가 의도치 않은 하위 path를 매치하지 않는지.
- `test_normalize_trigger_fallback_when_dl_not_fired` — 로드타임 이벤트 + DL 미발화 + URL 패턴 존재일 때 pageview 트리거 요구.

### test_spec_builder.py 케이스
- `test_build_specs_from_canplan_minimal` — 최소 CanPlan이 `GTMVariable/GTMTrigger/GTMTag`로 매끈히 떨어지는지.
- `test_build_specs_with_page_path_regex_trigger` — `matches_regex` + `{{Page Path}}` 조건이 GTM 필터 스펙으로 변환.
- `test_build_specs_with_click_trigger` — 클릭 트리거 + CJS 템플릿 변수(`cjs_template`)가 `type: "jsm"` 변수로 직렬화되는지.

---

## 새 케이스 추가 규칙

1. **데이터 픽스처는 함수 내부에 dict로 인라인**. 외부 YAML/JSON 의존 금지(회귀가 데이터 변경에 숨어들지 않도록).
2. **assert 메시지를 꼭 남긴다** (`assert cond, f"...{value=}"`). `py -3 tests/…` 실패 시 재현 포인트가 바로 보이게.
3. 새 이슈 코드/정책을 추가할 때는 **양성 + 음성** 케이스를 한 쌍으로 작성한다. 예: `DL_HEALTH_IGNORED` 통과 케이스 + 발동 케이스.
4. 파일 하단 `_run()`에 신규 `test_*` 함수를 **반드시 추가**한다(pytest 없이 돌려도 빠지지 않도록).
5. Playbook을 수정했으면 `tests/test_canplan_normalize.py`의 `_validate_trigger_fallback` 계열 케이스가 여전히 유효한지 점검.

---

## CI 의존성

현재는 수동 실행 기준이다. 필요해지면 루트에 `pytest.ini`/`conftest.py`를 추가하고, 이 문서에 진입 커맨드를 바꾼다. 외부 네트워크·Playwright·GTM API·OpenAI는 **어떤 테스트도 건드리지 않는다** — 모든 입력은 state dict에 고정돼 있다.
