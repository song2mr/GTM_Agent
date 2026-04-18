"""URL 휴리스틱 — PDP·장바구니 등 (탐색 재개 URL 결정용)."""

_PDP_MARKERS = (
    "goods_view",
    "goods_no=",
    "product/detail",
    "product_no=",
    "/goods/goods_view",
)

_CART_RESUME_MARKERS = (
    "/order/cart",
    "cart.php",
    "/basket",
    "shopping_cart",
    "/cart?",
)


def url_looks_like_pdp(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in _PDP_MARKERS)


def url_looks_like_cart_resume(url: str) -> bool:
    """순수 장바구니·바스켓 URL — add_to_cart 전용 노드는 PDP(`last_pdp_url`)로 재개하는 편이 안전."""
    u = (url or "").lower()
    if url_looks_like_pdp(u):
        return False
    return any(m in u for m in _CART_RESUME_MARKERS)
