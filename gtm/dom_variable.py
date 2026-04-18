"""GTM 웹 컨테이너 DOM Element 변수(type ``d``)용 parameter[] 정규화.

LLM 설계안은 `selector` / `attribute` 등 비공식 키를 쓰는 경우가 많아,
Tag Manager REST API가 기대하는 키(`selectionMethod`, `elementSelector` 또는
`elementId`, `attributeName`)로 맞춘다.

공식 리소스 스키마:
https://developers.google.com/tag-platform/tag-manager/api/reference/rest/v2/accounts.containers.workspaces.variables
"""

from __future__ import annotations

# GTM UI보내기·API에서 흔히 쓰이는 selectionMethod 값 (대소문자 혼용 방지용)
_SELECTION_CSS = "CSS_SELECTOR"
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
    up = s.upper().replace(" ", "_")
    if up == "ID":
        return _SELECTION_ID
    if up in ("CSS", "CSS_SELECTOR", "CSSSELECTOR"):
        return _SELECTION_CSS
    return None


def _infer_css_vs_id(
    method: str | None,
    element_id: str,
    selector: str,
) -> bool:
    """True = CSS_SELECTOR 모드, False = ID 모드."""
    if method == _SELECTION_CSS:
        return True
    if method == _SELECTION_ID:
        return False
    if selector and not element_id:
        return True
    if element_id and not selector:
        return False
    if selector and element_id:
        # 둘 다 있으면 셀렉터가 CSS처럼 보이면 CSS 우선
        s = selector
        if any(ch in s for ch in ".#[]*>,:()\"' "):
            return True
        return False
    return False


def normalize_dom_element_parameters(raw: list[dict]) -> list[dict]:
    """``type: \"d\"`` 변수의 ``parameter`` 배열을 GTM REST 형식으로 맞춘다.

    인식하는 별칭(템플릿 파라미터):
    - 선택 방식: ``selectionMethod``
    - CSS: ``elementSelector``, ``selector``, ``cssSelector``
    - ID: ``elementId``, ``element_id``
    - 속성: ``attributeName``, ``attribute``

    Raises:
        ValueError: DOM 대상 값이 비어 있어 API가 거절할 때(사전 검증).
    """
    m = _collect_template_map(raw)

    element_id = _first_non_empty(
        m,
        ("elementId", "element_id"),
    )
    selector = _first_non_empty(
        m,
        ("elementSelector", "selector", "cssSelector"),
    )
    attribute = _first_non_empty(
        m,
        ("attributeName", "attribute"),
    )

    method = _normalize_method_token(_first_non_empty(m, ("selectionMethod",)))
    use_css = _infer_css_vs_id(method, element_id, selector)

    if use_css:
        if not selector:
            raise ValueError(
                "DOM 변수(type d): CSS 선택이 필요한데 elementSelector/selector 값이 비어 있습니다."
            )
        return [
            {"type": "template", "key": "selectionMethod", "value": _SELECTION_CSS},
            {"type": "template", "key": "elementSelector", "value": selector},
            {"type": "template", "key": "attributeName", "value": attribute},
        ]

    if not element_id:
        raise ValueError(
            "DOM 변수(type d): Element ID 선택이 필요한데 elementId 값이 비어 있습니다."
        )
    return [
        {"type": "template", "key": "selectionMethod", "value": _SELECTION_ID},
        {"type": "template", "key": "elementId", "value": element_id},
        {"type": "template", "key": "attributeName", "value": attribute},
    ]
