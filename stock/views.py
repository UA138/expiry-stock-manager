import datetime

from django.http import JsonResponse
from django.shortcuts import render

# 画面確認用のダミーデータ（DB未接続）
DUMMY_CATEGORIES = [
    {"code": "C001", "name": "乳製品"},
    {"code": "C002", "name": "インスタント食品"},
    {"code": "C003", "name": "缶詰"},
    {"code": "C004", "name": "ベーカリー"},
    {"code": "C005", "name": "飲料"},
]

# 同じ商品コードでも、仕入れタイミングが違えば賞味期限が異なる「ロット」として複数行を持てる
DUMMY_STOCKS = [
    {"id": 1, "product_code": "P0001", "jan_code": "4901234567890", "name": "牛乳 1L", "category": "乳製品", "store_quantity": 8, "warehouse_quantity": 4, "expiry_date": datetime.date(2026, 6, 29)},
    {"id": 6, "product_code": "P0001", "jan_code": "4901234567890", "name": "牛乳 1L", "category": "乳製品", "store_quantity": 5, "warehouse_quantity": 5, "expiry_date": datetime.date(2026, 7, 10)},
    {"id": 2, "product_code": "P0002", "jan_code": "4901234567891", "name": "ヨーグルト 4個パック", "category": "乳製品", "store_quantity": 20, "warehouse_quantity": 10, "expiry_date": datetime.date(2026, 7, 2)},
    {"id": 3, "product_code": "P0003", "jan_code": "4901234567892", "name": "カップ麺", "category": "インスタント食品", "store_quantity": 30, "warehouse_quantity": 20, "expiry_date": datetime.date(2026, 12, 1)},
    {"id": 4, "product_code": "P0004", "jan_code": "4901234567893", "name": "缶詰（さば）", "category": "缶詰", "store_quantity": 5, "warehouse_quantity": 3, "expiry_date": datetime.date(2026, 6, 25)},
    {"id": 5, "product_code": "P0005", "jan_code": "4901234567894", "name": "パン", "category": "ベーカリー", "store_quantity": 12, "warehouse_quantity": 3, "expiry_date": datetime.date(2026, 6, 30)},
]

DUMMY_USERS = [
    {"id": 1, "username": "admin", "role": "管理者"},
    {"id": 2, "username": "staff01", "role": "スタッフ"},
]

# 出庫予定（出荷日・出荷数があらかじめ確定している前提のダミーデータ）
DUMMY_SHIPMENTS = [
    {"id": 1, "product_code": "P0001", "location": "store", "ship_date": datetime.date(2026, 7, 1), "ship_quantity": 6},
    {"id": 2, "product_code": "P0001", "location": "warehouse", "ship_date": datetime.date(2026, 7, 5), "ship_quantity": 3},
    {"id": 3, "product_code": "P0003", "location": "store", "ship_date": datetime.date(2026, 7, 15), "ship_quantity": 10},
]


def _expiry_status(expiry_date):
    today = datetime.date(2026, 6, 28)
    days_left = (expiry_date - today).days
    if days_left < 0:
        return "expired"
    if days_left <= 3:
        return "warning"
    return "ok"


def login_view(request):
    return render(request, "stock/login.html")


def stock_list_view(request):
    stocks = []
    for item in DUMMY_STOCKS:
        stocks.append({
            **item,
            "total_quantity": item["store_quantity"] + item["warehouse_quantity"],
            "status": _expiry_status(item["expiry_date"]),
        })
    return render(request, "stock/stock_list.html", {"stocks": stocks})


def stock_register_view(request):
    return render(request, "stock/stock_form.html", {
        "mode": "register",
        "categories": DUMMY_CATEGORIES,
    })


def stock_edit_view(request, pk):
    item = next((s for s in DUMMY_STOCKS if s["id"] == pk), DUMMY_STOCKS[0])
    return render(request, "stock/stock_form.html", {
        "mode": "edit",
        "categories": DUMMY_CATEGORIES,
        "item": item,
    })


def stock_receive_view(request):
    return render(request, "stock/stock_receive.html", {
        "stocks": DUMMY_STOCKS,
    })


def product_lookup_api(request, product_code):
    """商品コードから商品マスタの情報を返すAPI（今はダミーデータ、後でDB検索に差し替える）"""
    lots = [s for s in DUMMY_STOCKS if s["product_code"] == product_code]
    if not lots:
        return JsonResponse({"error": "not_found"}, status=404)
    first = lots[0]
    return JsonResponse({
        "product_code": first["product_code"],
        "jan_code": first["jan_code"],
        "name": first["name"],
        "category": first["category"],
        "store_quantity": sum(lot["store_quantity"] for lot in lots),
        "warehouse_quantity": sum(lot["warehouse_quantity"] for lot in lots),
    })


def stock_ship_view(request):
    return render(request, "stock/stock_ship.html", {
        "stocks": DUMMY_STOCKS,
    })


def _project_stock(target_date):
    """指定日付までの出庫予定をFEFO（賞味期限が近い順）で各ロットから差し引いた予測在庫を計算する"""
    shipments_by_product = {}
    for shipment in DUMMY_SHIPMENTS:
        if shipment["ship_date"] > target_date:
            continue
        totals = shipments_by_product.setdefault(shipment["product_code"], {"store": 0, "warehouse": 0})
        totals[shipment["location"]] += shipment["ship_quantity"]

    lots_by_product = {}
    for lot in DUMMY_STOCKS:
        lots_by_product.setdefault(lot["product_code"], []).append(lot)

    results = []
    for product_code, lots in lots_by_product.items():
        sorted_lots = sorted(lots, key=lambda lot: lot["expiry_date"])
        remaining = dict(shipments_by_product.get(product_code, {"store": 0, "warehouse": 0}))
        for lot in sorted_lots:
            projected_store = lot["store_quantity"]
            projected_warehouse = lot["warehouse_quantity"]
            consume_store = min(remaining["store"], projected_store)
            projected_store -= consume_store
            remaining["store"] -= consume_store
            consume_warehouse = min(remaining["warehouse"], projected_warehouse)
            projected_warehouse -= consume_warehouse
            remaining["warehouse"] -= consume_warehouse
            results.append({
                "product_code": lot["product_code"],
                "name": lot["name"],
                "expiry_date": lot["expiry_date"],
                "projected_store_quantity": projected_store,
                "projected_warehouse_quantity": projected_warehouse,
            })
        if remaining["store"] > 0 or remaining["warehouse"] > 0:
            results.append({
                "product_code": product_code,
                "name": lots[0]["name"],
                "shortage": True,
                "shortage_store": remaining["store"],
                "shortage_warehouse": remaining["warehouse"],
            })
    return results


def stock_projection_view(request):
    target_date_str = request.GET.get("target_date")
    target_date = None
    projections = None
    if target_date_str:
        try:
            target_date = datetime.date.fromisoformat(target_date_str)
            projections = _project_stock(target_date)
        except ValueError:
            target_date = None
    return render(request, "stock/stock_projection.html", {
        "target_date": target_date_str or "",
        "projections": projections,
    })


def master_view(request):
    return render(request, "stock/master.html", {
        "categories": DUMMY_CATEGORIES,
        "users": DUMMY_USERS,
        "products": DUMMY_STOCKS,
    })
