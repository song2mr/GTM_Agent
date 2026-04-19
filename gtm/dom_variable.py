"""GTM 웹 컨테이너 DOM Element 변수(type ``d``)용 parameter[] 정규화.

공식 Variable Dictionary Reference가 문서화한 DOM Element 변수 파라미터는
``elementId`` / ``attributeName`` 뿐이다(HTML ``id`` 기반 선택). GTM UI에는
CSS Selector 모드가 존재하지만 REST API에서는 공개 스펙이 없고, 비공식 키를
보내면 서버가 조용히 무시 → 남은 ``elementId``가 비었다며 ``vendorTemplate.
parameter.elementId: The value must not be empty.`` 400을 돌려준다.

이 프로젝트의 처리 방침:

1. **ID 모드**(HTML id로 선택)면 공식 스펙 그대로 ``type: "d"`` 변수를 만든다.
2. **CSS 모드**면 ``type: "jsm"`` (Custom JavaScript) 변수로 **자동 변환**한다.
   변수 이름은 유지되므로 Tag/CJS에서 ``{{DOM - item_name}}`` 참조가 그대로 동작한다.

공식 스펙 근거:
https://web.archive.org/web/2024/https://developers.google.com/tag-platform/tag-manager/api/v1/variable-dictionary-reference
"""

from __future__ import annotations

import json

_SELECTION_CSS = "CSS"
_SELECTION_ID = "ID"


def _collect_template_map(params: list[dict]) -> dict[str, str]:
    m: dict[str, str] = {}
    for p in params:
        if p.get("type") != "template":
            continue
        key = (p.get("key") or "").strip()
        if not key:
            continue
        m[key] = str(p.get("value", ""))
    return m


def _first_non_empty(m: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in m and (m[k] or "").strip():
            return m[k].strip()
    return ""


def _normalize_method_token(raw: str) -> str | None:
    if not (raw or "").strip():
        return None
    s = raw.strip()
    low = s.lower().replace(" ", "").replace("_", "")
    if low in ("id", "elementid"):
        return _SELECTION_ID
    if low in ("css", "cssselector", "selector"):
        return _SELECTION_CSS
    return None


def _infer_css_vs_id(
    method: str | None,
    element_id: str,
    selector: str,
) -> bool:
    """True = CSS 모드(= jsm 변환 대상), False = ID 모드(= type d 유지)."""
    if method == _SELECTION_CSS:
        return True
    if method == _SELECTION_ID:
        return False
    if selector and not element_id:
        return True
    if element_id and not selector:
        return False
    if selector and element_id:
        s = selector
        if any(ch in s for ch in ".#[]*>,:()\"' "):
            return True
        return False
    return False


def _build_css_extractor_js(selector: str, attribute: str) -> str:
    """CSS selector + 선택적 속성명을 읽는 최소 JSM 함수 본문을 생성한다.

    - ``attributeName``이 비어 있으면 ``textContent.trim()``
    - 있으면 ``getAttribute(attr)``
    - 요소가 없으면 빈 문자열
    """
    sel = json.dumps(selector)
    attr = json.dumps(attribute or "")
    return (
        "function(){"
        f"var el=document.querySelector({sel});"
        "if(!el)return '';"
        f"var a={attr};"
        "return a?(el.getAttribute(a)||''):((el.textContent||'').trim());"
        "}"
    )


def normalize_dom_element_parameters(
    raw: list[dict],
) -> tuple[str, list[dict]] | None:
    """DOM 변수 설계안을 **실제 GTM 리소스 스펙**으로 정규화한다.

    Returns:
        ``(new_type, parameters)`` 튜플. 입력이 비어 있거나 정규화 불가한 경우 ``None``.

        - ID 모드: ``("d", [elementId, attributeName])`` — 공식 DOM Element 변수.
        - CSS 모드: ``("jsm", [javascript])`` — Custom JavaScript 변수로 변환.

    인식하는 별칭(템플릿 파라미터):
    - 선택 방식: ``selectionMethod`` (``ID`` / ``CSS`` 및 일부 동의어)
    - CSS 셀렉터: ``elementSelector``, ``selector``, ``cssSelector``
    - ID: ``elementId``, ``element_id``
    - 속성: ``attributeName``, ``attribute``
    """
    m = _collect_template_map(raw)

    element_id = _first_non_empty(m, ("elementId", "element_id"))
    selector = _first_non_empty(
        m, ("elementSelector", "selector", "cssSelector")
    )
    attribute = _first_non_empty(m, ("attributeName", "attribute"))

    method = _normalize_method_token(_first_non_empty(m, ("selectionMethod",)))
    use_css = _infer_css_vs_id(method, element_id, selector)

    if use_css:
        if not selector:
            return None
        js = _build_css_extractor_js(selector, attribute)
        return (
            "jsm",
            [{"type": "template", "key": "javascript", "value": js}],
        )

    if not element_id:
        return None

    return (
        "d",
        [
            {"type": "template", "key": "elementId", "value": element_id},
            {"type": "template", "key": "attributeName", "value": attribute},
        ],
    )
