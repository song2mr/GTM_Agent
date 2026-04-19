"""Custom JS template registry for CanPlan.

LLM이 자유 작성한 자바스크립트 본문을 GTM 변수에 박지 않는다.
이 레지스트리에 선등록된 템플릿 ID + 인자만 허용(§8).
"""

from __future__ import annotations

import json


REGISTERED_TEMPLATES: set[str] = {
    "attr_from_selector",
    "text_to_number",
    "json_ld_value",
    "items_from_jsonld",
    "items_from_dom",
    "build_single_item",
    "meta_tag_value",
    "cookie_value",
}


def is_registered(template_id: str) -> bool:
    return template_id in REGISTERED_TEMPLATES


def _js_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _safe_obj_ref(obj_expr: str, keys: list[str]) -> str:
    """JS `obj?.a?.b?.c` 같은 접근을 안전한 형태로 합성."""
    parts = [obj_expr]
    for k in keys:
        parts.append(f"&&({parts[-1]})[{_js_quote(k)}]")
    return "(" + "".join(parts) + ")"


def _mapping_js_object(mapping: dict) -> str:
    """GA4 필드명 ↔ JSON-LD 경로 매핑을 JS 객체 리터럴로."""
    items = []
    for ga_field, path in mapping.items():
        items.append(f"{_js_quote(str(ga_field))}: {_js_quote(str(path))}")
    return "{" + ",".join(items) + "}"


def _dom_item_fields_js(item_fields: dict) -> str:
    """PLP/카트 각 카드 → {ga4 field: {selector, attribute}} 매핑을 JS로."""
    rows = []
    for ga_field, spec in item_fields.items():
        selector = spec.get("selector", "") if isinstance(spec, dict) else str(spec)
        attribute = (spec.get("attribute") if isinstance(spec, dict) else None) or "textContent"
        rows.append(
            "{"
            f"field:{_js_quote(ga_field)},"
            f"selector:{_js_quote(selector)},"
            f"attribute:{_js_quote(attribute)}"
            "}"
        )
    return "[" + ",".join(rows) + "]"


def render_template(template_id: str, args: dict) -> str:
    """Render pre-approved template into GTM Custom JS body.

    반환 문자열은 GTM Custom JS 변수의 ``javascript`` 파라미터에 그대로 들어간다.
    모든 템플릿은 예외 발생 시 ``undefined`` 를 반환하여 태그 전체를 멈추지 않는다.
    알 수 없는 template_id는 정규화가 먼저 거부하지만, 방어적으로 ``undefined`` 반환.
    """
    args = dict(args or {})

    if template_id == "attr_from_selector":
        selector = str(args.get("selector", "")).strip()
        attribute = str(args.get("attribute", "") or "textContent").strip()
        if not selector:
            return "function(){return undefined;}"
        if attribute == "textContent":
            return (
                "function(){try{var el=document.querySelector("
                f"{_js_quote(selector)}"
                ");if(!el)return undefined;return (el.textContent||'').trim();}"
                "catch(e){return undefined;}}"
            )
        return (
            "function(){try{var el=document.querySelector("
            f"{_js_quote(selector)}"
            ");if(!el)return undefined;return (el.getAttribute("
            f"{_js_quote(attribute)}"
            ")||'').trim();}catch(e){return undefined;}}"
        )

    if template_id == "text_to_number":
        source_var = str(args.get("source_var", "")).strip()
        selector = str(args.get("selector", "")).strip()
        if source_var:
            source_expr = source_var
        elif selector:
            source_expr = (
                "(function(){var el=document.querySelector("
                f"{_js_quote(selector)}"
                ");return el?(el.textContent||''):'';})()"
            )
        else:
            source_expr = "''"
        return (
            "function(){try{var raw="
            + source_expr
            + ";if(raw===undefined||raw===null)return undefined;"
            + "var n=String(raw).replace(/[^0-9.-]/g,'');"
            + "if(!n)return undefined;var v=parseFloat(n);"
            + "return Number.isFinite(v)?v:undefined;}catch(e){return undefined;}}"
        )

    if template_id == "json_ld_value":
        path = str(args.get("path", "")).strip()
        if not path:
            return "function(){return undefined;}"
        return (
            "function(){try{var tags=document.querySelectorAll("
            "'script[type=\"application/ld+json\"]');"
            "var keyPath="
            + _js_quote(path)
            + ".split('.');"
            "for(var i=0;i<tags.length;i++){"
            "var obj=JSON.parse(tags[i].textContent||'{}');"
            "var cur=obj;for(var j=0;j<keyPath.length;j++){"
            "if(cur==null)break;cur=cur[keyPath[j]];}"
            "if(cur!==undefined&&cur!==null&&cur!=='')return cur;}"
            "return undefined;}catch(e){return undefined;}}"
        )

    if template_id == "items_from_jsonld":
        mapping = args.get("mapping") or {
            "item_name": "name",
            "item_id": "sku",
            "price": "offers.price",
            "currency": "offers.priceCurrency",
            "item_brand": "brand.name",
            "item_category": "category",
        }
        return (
            "function(){try{"
            "var tags=document.querySelectorAll('script[type=\"application/ld+json\"]');"
            "var mapping=" + _mapping_js_object(mapping) + ";"
            "function getPath(obj,path){var parts=String(path||'').split('.');var c=obj;"
            "for(var i=0;i<parts.length;i++){if(c==null)return undefined;c=c[parts[i]];}"
            "return c;}"
            "function buildItem(src){var out={};for(var k in mapping){"
            "var v=getPath(src,mapping[k]);if(v!==undefined&&v!==null&&v!=='') out[k]=v;}"
            "if(out.price!=null){var n=parseFloat(String(out.price).replace(/[^0-9.-]/g,''));"
            "if(Number.isFinite(n))out.price=n;} return out;}"
            "for(var i=0;i<tags.length;i++){"
            "try{var obj=JSON.parse(tags[i].textContent||'{}');"
            "if(!obj)continue;"
            "if(Array.isArray(obj.itemListElement)){"
            "var arr=[];for(var j=0;j<obj.itemListElement.length;j++){"
            "var it=obj.itemListElement[j];var src=it&&it.item?it.item:it;"
            "arr.push(buildItem(src));}"
            "if(arr.length)return arr;}"
            "if(obj['@type']&&/Product/i.test(obj['@type']))return [buildItem(obj)];"
            "}catch(e){}}"
            "return undefined;"
            "}catch(e){return undefined;}}"
        )

    if template_id == "items_from_dom":
        list_selector = str(args.get("list_selector", "")).strip()
        item_fields = args.get("item_fields") or {}
        if not list_selector or not item_fields:
            return "function(){return undefined;}"
        fields_js = _dom_item_fields_js(item_fields)
        return (
            "function(){try{"
            "var nodes=document.querySelectorAll(" + _js_quote(list_selector) + ");"
            "if(!nodes||!nodes.length)return undefined;"
            "var fields=" + fields_js + ";"
            "var arr=[];for(var i=0;i<nodes.length;i++){var n=nodes[i];var row={};"
            "for(var f=0;f<fields.length;f++){var fd=fields[f];"
            "try{var el=n.querySelector(fd.selector);if(!el)continue;"
            "var v=fd.attribute==='textContent'?(el.textContent||'').trim():(el.getAttribute(fd.attribute)||'').trim();"
            "if(v===''||v==null)continue;"
            "if(fd.field==='price'){var num=parseFloat(String(v).replace(/[^0-9.-]/g,''));"
            "if(Number.isFinite(num))row.price=num;else continue;}"
            "else{row[fd.field]=v;}"
            "}catch(e){}}"
            "if(Object.keys(row).length)arr.push(row);}"
            "return arr.length?arr:undefined;"
            "}catch(e){return undefined;}}"
        )

    if template_id == "build_single_item":
        # fields_from: {ga4_field: "{{VariableName}}"} — GTM이 값으로 치환해 삽입.
        fields_from = args.get("fields_from") or {}
        if not fields_from:
            return "function(){return undefined;}"
        entries = []
        for ga_field, var_ref in fields_from.items():
            ref = str(var_ref)
            if not ref.startswith("{{"):
                ref = "{{" + ref + "}}"
            entries.append(f"{_js_quote(str(ga_field))}: {ref}")
        return (
            "function(){try{var item={" + ",".join(entries) + "};"
            "var clean={};for(var k in item){var v=item[k];"
            "if(v===undefined||v===null||v==='')continue;"
            "if(k==='price'||k==='value'){var n=parseFloat(String(v).replace(/[^0-9.-]/g,''));"
            "if(Number.isFinite(n))clean[k]=n;}"
            "else{clean[k]=v;}}"
            "return Object.keys(clean).length?[clean]:undefined;"
            "}catch(e){return undefined;}}"
        )

    if template_id == "meta_tag_value":
        prop = str(args.get("property", "")).strip()
        name_attr = str(args.get("name", "")).strip()
        selector = ""
        if prop:
            selector = f"meta[property={_js_quote(prop)}]"
        elif name_attr:
            selector = f"meta[name={_js_quote(name_attr)}]"
        if not selector:
            return "function(){return undefined;}"
        return (
            "function(){try{var el=document.querySelector("
            + selector
            + ");if(!el)return undefined;"
            "var v=(el.getAttribute('content')||'').trim();"
            "return v||undefined;}catch(e){return undefined;}}"
        )

    if template_id == "cookie_value":
        cookie_name = str(args.get("cookie_name", "")).strip()
        if not cookie_name:
            return "function(){return undefined;}"
        return (
            "function(){try{var name=" + _js_quote(cookie_name) + "+'=';"
            "var parts=(document.cookie||'').split(';');"
            "for(var i=0;i<parts.length;i++){var p=parts[i].replace(/^\\s+/,'');"
            "if(p.indexOf(name)===0)return decodeURIComponent(p.substring(name.length));}"
            "return undefined;}catch(e){return undefined;}}"
        )

    # Unknown templates are guarded by normalize, but keep safe fallback.
    return "function(){return undefined;}"
