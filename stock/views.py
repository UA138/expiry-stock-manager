import csv
import datetime
from collections import defaultdict
from urllib.parse import quote, urlencode

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from .models import Category, Product, ReceiveHistory, ShipmentPlan, StockLot

# ── ダミーデータ（入庫履歴・出庫履歴の表示用。DB実装まで使用） ────────────────
DUMMY_RECEIVE_HISTORY = [
    {"id": 1, "received_at": datetime.date(2026, 7, 1),  "product_code": "P0001", "jan_code": "4901234567890", "name": "牛乳 1L",           "category": "乳製品",           "expiry_date": datetime.date(2026, 7, 20), "location": "store",     "quantity": 12,  "remarks": ""},
    {"id": 2, "received_at": datetime.date(2026, 7, 1),  "product_code": "P0002", "jan_code": "4901234567891", "name": "ヨーグルト 4個パック", "category": "乳製品",           "expiry_date": datetime.date(2026, 7, 12), "location": "store",     "quantity": 24,  "remarks": ""},
    {"id": 3, "received_at": datetime.date(2026, 7, 2),  "product_code": "P0003", "jan_code": "4901234567892", "name": "カップ麺",             "category": "インスタント食品", "expiry_date": datetime.date(2026, 12, 1), "location": "warehouse", "quantity": 50,  "remarks": ""},
    {"id": 4, "received_at": datetime.date(2026, 7, 3),  "product_code": "P0001", "jan_code": "4901234567890", "name": "牛乳 1L",             "category": "乳製品",           "expiry_date": datetime.date(2026, 7, 15), "location": "warehouse", "quantity": 10,  "remarks": "ロットB"},
    {"id": 5, "received_at": datetime.date(2026, 7, 5),  "product_code": "P0004", "jan_code": "4901234567893", "name": "缶詰（さば）",         "category": "缶詰",             "expiry_date": datetime.date(2027, 6, 25), "location": "store",     "quantity": 24,  "remarks": ""},
    {"id": 6, "received_at": datetime.date(2026, 7, 5),  "product_code": "P0005", "jan_code": "4901234567894", "name": "パン",                 "category": "ベーカリー",       "expiry_date": datetime.date(2026, 7, 9),  "location": "store",     "quantity": 20,  "remarks": ""},
    {"id": 7, "received_at": datetime.date(2026, 7, 5),  "product_code": "P0003", "jan_code": "4901234567892", "name": "カップ麺",             "category": "インスタント食品", "expiry_date": datetime.date(2026, 12, 1), "location": "store",     "quantity": -3,  "remarks": "不良品返品"},
]


# ── ヘルパー関数 ──────────────────────────────────────────────────────────────
def _expiry_status(expiry_date):
    days_left = (expiry_date - datetime.date.today()).days
    if days_left < 0:
        return "expired"
    if days_left <= 3:
        return "warning"
    return "ok"


def _mall_status(expiry_date, mall_limit_days):
    if mall_limit_days is None:
        return "mall_ok"
    days_left = (expiry_date - datetime.date.today()).days
    if days_left <= mall_limit_days:
        return "mall_ng"
    if days_left <= mall_limit_days + 5:
        return "mall_warning"
    return "mall_ok"


def _filter_history(records, date_field, params):
    """日付条件でダミー履歴レコードを絞り込む"""
    date_mode = params.get("date_mode", "single")
    try:
        if date_mode == "single":
            d = params.get("single_date", "")
            if d:
                target = datetime.date.fromisoformat(d)
                return [r for r in records if r[date_field] == target]
        else:
            date_from = params.get("date_from", "")
            date_to   = params.get("date_to", "")
            result = list(records)
            if date_from:
                df = datetime.date.fromisoformat(date_from)
                result = [r for r in result if r[date_field] >= df]
            if date_to:
                dt = datetime.date.fromisoformat(date_to)
                result = [r for r in result if r[date_field] <= dt]
            return result
    except ValueError:
        pass
    return list(records)


# ── 認証 ─────────────────────────────────────────────────────────────────────
def login_view(request):
    return render(request, "stock/login.html")


# ── 在庫一覧（DB版） ──────────────────────────────────────────────────────────
def stock_list_view(request):
    all_lots = StockLot.objects.select_related("product__category").order_by(
        "product__product_code", "expiry_date"
    )

    # 商品コードをキーに全ロットの合計を集計
    product_totals = defaultdict(lambda: {"store": 0, "warehouse": 0})
    for lot in all_lots:
        t = product_totals[lot.product.product_code]
        t["store"]     += lot.store_quantity
        t["warehouse"] += lot.warehouse_quantity

    stocks = []
    for lot in all_lots:
        t = product_totals[lot.product.product_code]
        stocks.append({
            "id":                 lot.id,
            "product_code":       lot.product.product_code,
            "jan_code":           lot.product.jan_code,
            "name":               lot.product.name,
            "category":           lot.product.category.name,
            "store_quantity":     lot.store_quantity,
            "warehouse_quantity": lot.warehouse_quantity,
            "total_quantity":     t["store"] + t["warehouse"],
            "expiry_date":        lot.expiry_date,
            "status":             _expiry_status(lot.expiry_date),
            "mall_status":        _mall_status(lot.expiry_date, lot.product.mall_limit_days),
        })
    return render(request, "stock/stock_list.html", {"stocks": stocks})


# ── 在庫登録・編集（暫定：DB未連携） ─────────────────────────────────────────
def stock_register_view(request):
    categories = Category.objects.all()
    return render(request, "stock/stock_form.html", {
        "mode": "register",
        "categories": categories,
    })


def stock_edit_view(request, pk):
    try:
        lot = StockLot.objects.select_related("product__category").get(pk=pk)
    except StockLot.DoesNotExist:
        return redirect("stock:stock_list")
    return render(request, "stock/stock_form.html", {
        "mode": "edit",
        "categories": Category.objects.all(),
        "item": {
            "id":                 lot.id,
            "product_code":       lot.product.product_code,
            "jan_code":           lot.product.jan_code,
            "name":               lot.product.name,
            "category":           lot.product.category.name,
            "store_quantity":     lot.store_quantity,
            "warehouse_quantity": lot.warehouse_quantity,
            "expiry_date":        lot.expiry_date,
        },
    })


# ── 棚卸し（DB版） ────────────────────────────────────────────────────────────
def stocktake_view(request):
    if request.method == "POST":
        with transaction.atomic():
            updated = 0
            for lot in StockLot.objects.all():
                store_val = request.POST.get(f"store_{lot.id}", "").strip()
                wh_val    = request.POST.get(f"warehouse_{lot.id}", "").strip()
                changed = False
                if store_val != "":
                    lot.store_quantity = int(store_val)
                    changed = True
                if wh_val != "":
                    lot.warehouse_quantity = int(wh_val)
                    changed = True
                if changed:
                    lot.save()
                    updated += 1
        messages.success(request, f"棚卸しデータを保存しました（{updated}ロット更新）。")
        return redirect("stock:stocktake")

    lots = StockLot.objects.select_related("product").order_by(
        "product__product_code", "expiry_date"
    )
    stocks = [{
        "id":                 lot.id,
        "product_code":       lot.product.product_code,
        "name":               lot.product.name,
        "expiry_date":        lot.expiry_date,
        "store_quantity":     lot.store_quantity,
        "warehouse_quantity": lot.warehouse_quantity,
        "total_quantity":     lot.store_quantity + lot.warehouse_quantity,
        "status":             _expiry_status(lot.expiry_date),
    } for lot in lots]
    return render(request, "stock/stocktake.html", {"stocks": stocks})


# ── 入庫登録（POST保存は後でDB連携） ─────────────────────────────────────────
def stock_receive_view(request):
    if request.method == "POST":
        messages.success(request, "入庫登録が完了しました。")
        return redirect("stock:stock_receive")
    return render(request, "stock/stock_receive.html")


# ── 入出庫登録（タブ統合版） ──────────────────────────────────────────────────
def inout_view(request):
    tab = request.GET.get("tab", "receive")

    if request.method == "POST":
        tab_post = request.POST.get("tab", "receive")

        if tab_post == "receive":
            # 入庫：DB連携は後で実装
            messages.success(request, "入庫登録が完了しました。")
            return redirect(f"{request.path}?tab=receive")

        else:
            # 出庫：ShipmentPlanに仮データとして保存
            ship_date_str = request.POST.get("ship_date", "").strip()
            try:
                ship_date = datetime.date.fromisoformat(ship_date_str) if ship_date_str else datetime.date.today()
            except ValueError:
                ship_date = datetime.date.today()

            row_indices = sorted({
                key.split("_")[-1]
                for key in request.POST.keys()
                if key.startswith("product_code_")
            })

            registered = 0
            errors = []
            for idx in row_indices:
                product_code = request.POST.get(f"product_code_{idx}", "").strip()
                if not product_code:
                    continue
                try:
                    product = Product.objects.get(product_code=product_code)
                except Product.DoesNotExist:
                    errors.append(f"商品コード「{product_code}」は登録されていません")
                    continue

                qty_str = request.POST.get(f"quantity_{idx}", "").strip()
                try:
                    quantity = int(qty_str)
                    if quantity <= 0:
                        raise ValueError
                except ValueError:
                    errors.append(f"出荷数は1以上の数値を入力してください（商品コード: {product_code}）")
                    continue

                ShipmentPlan.objects.create(
                    product=product,
                    ship_date=ship_date,
                    location=request.POST.get(f"location_{idx}", "store"),
                    quantity=quantity,
                    remarks=request.POST.get(f"remarks_{idx}", "")[:30],
                    is_confirmed=False,
                )
                registered += 1

            if registered > 0:
                messages.success(request, f"{registered}件の出庫予定を登録しました（仮データ）。")
            for err in errors:
                messages.warning(request, err)
            return redirect(f"{request.path}?tab=ship")

    return render(request, "stock/stock_inout.html", {"tab": tab})


# ── 出庫登録（DB版：ShipmentPlan に仮データとして保存） ───────────────────────
def stock_ship_view(request):
    if request.method == "POST":
        ship_date_str = request.POST.get("ship_date", "").strip()
        try:
            ship_date = datetime.date.fromisoformat(ship_date_str) if ship_date_str else datetime.date.today()
        except ValueError:
            ship_date = datetime.date.today()

        # フォームの行インデックスを収集
        row_indices = sorted({
            key.split("_")[-1]
            for key in request.POST.keys()
            if key.startswith("product_code_")
        })

        registered = 0
        errors = []
        for idx in row_indices:
            product_code = request.POST.get(f"product_code_{idx}", "").strip()
            if not product_code:
                continue
            try:
                product = Product.objects.get(product_code=product_code)
            except Product.DoesNotExist:
                errors.append(f"商品コード「{product_code}」は登録されていません")
                continue

            qty_str = request.POST.get(f"quantity_{idx}", "").strip()
            try:
                quantity = int(qty_str)
                if quantity <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"{product.name}：出荷数は1以上の数値を入力してください")
                continue

            location = request.POST.get(f"location_{idx}", "store")
            remarks  = request.POST.get(f"remarks_{idx}", "")[:30]

            ShipmentPlan.objects.create(
                product=product,
                ship_date=ship_date,
                location=location,
                quantity=quantity,
                remarks=remarks,
                is_confirmed=False,
            )
            registered += 1

        if registered > 0:
            messages.success(request, f"{registered}件の出庫予定を登録しました（仮データ）。")
        for err in errors:
            messages.warning(request, err)
        return redirect("stock:stock_ship")

    return render(request, "stock/stock_ship.html")


# ── 出庫管理：一覧・一括削除・確定（DB版） ────────────────────────────────────
def shipment_manage_view(request):
    date_from_str = request.GET.get("date_from", "").strip()
    date_to_str   = request.GET.get("date_to", "").strip()
    searched      = bool(date_from_str or date_to_str)

    def _build_queryset(df_str, dt_str):
        qs = ShipmentPlan.objects.filter(is_confirmed=False).select_related("product")
        if df_str:
            try:
                qs = qs.filter(ship_date__gte=datetime.date.fromisoformat(df_str))
            except ValueError:
                pass
        if dt_str:
            try:
                qs = qs.filter(ship_date__lte=datetime.date.fromisoformat(dt_str))
            except ValueError:
                pass
        return qs.order_by("ship_date", "product__product_code")

    if request.method == "POST":
        action     = request.POST.get("action")
        df_post    = request.POST.get("date_from", "").strip()
        dt_post    = request.POST.get("date_to", "").strip()
        target_qs  = _build_queryset(df_post, dt_post)

        if action == "delete":
            count = target_qs.count()
            target_qs.delete()
            messages.success(request, f"{count}件の仮データを削除しました。")

        elif action == "confirm":
            plan_list = list(target_qs.select_related("product"))
            if not plan_list:
                messages.warning(request, "確定する対象がありません。")
            else:
                with transaction.atomic():
                    # 商品×場所ごとに出荷数を集計
                    totals = defaultdict(lambda: {"store": 0, "warehouse": 0})
                    for plan in plan_list:
                        totals[plan.product.product_code][plan.location] += plan.quantity

                    shortage_msgs = []
                    for product_code, amounts in totals.items():
                        lots = StockLot.objects.filter(
                            product__product_code=product_code
                        ).order_by("expiry_date")

                        remaining = {"store": amounts["store"], "warehouse": amounts["warehouse"]}
                        for lot in lots:
                            # FEFO：店頭
                            consume_s = min(remaining["store"], max(0, lot.store_quantity))
                            lot.store_quantity -= consume_s
                            remaining["store"] -= consume_s
                            # FEFO：倉庫
                            consume_w = min(remaining["warehouse"], max(0, lot.warehouse_quantity))
                            lot.warehouse_quantity -= consume_w
                            remaining["warehouse"] -= consume_w
                            lot.save()

                        if remaining["store"] > 0 or remaining["warehouse"] > 0:
                            shortage_msgs.append(
                                f"{product_code}：在庫不足（店頭 {remaining['store']}個 / 倉庫 {remaining['warehouse']}個 不足）"
                            )

                    now = datetime.datetime.now()
                    target_qs.update(is_confirmed=True, confirmed_at=now)

                messages.success(request, f"{len(plan_list)}件を確定し、在庫に反映しました。")
                for msg in shortage_msgs:
                    messages.warning(request, msg)

        return redirect(
            f"{request.path}?date_from={request.POST.get('date_from', '')}&date_to={request.POST.get('date_to', '')}"
        )

    plans = _build_queryset(date_from_str, date_to_str) if searched else []
    total_qty = sum(p.quantity for p in plans) if searched else 0

    return render(request, "stock/shipment_manage.html", {
        "plans":     plans,
        "searched":  searched,
        "date_from": date_from_str,
        "date_to":   date_to_str,
        "total_qty": total_qty,
    })


# ── 在庫照会（DB版：ShipmentPlan でFEFO計算） ────────────────────────────────
def _project_stock(target_date):
    plans = ShipmentPlan.objects.filter(
        ship_date__lte=target_date
    ).select_related("product")

    shipments_by_product = defaultdict(lambda: {"store": 0, "warehouse": 0})
    for plan in plans:
        shipments_by_product[plan.product.product_code][plan.location] += plan.quantity

    lots_by_product = defaultdict(list)
    for lot in StockLot.objects.select_related("product").order_by("expiry_date"):
        lots_by_product[lot.product.product_code].append(lot)

    results = []
    for product_code, lots in lots_by_product.items():
        remaining = dict(shipments_by_product.get(product_code, {"store": 0, "warehouse": 0}))
        for lot in lots:
            proj_store = lot.store_quantity
            proj_wh    = lot.warehouse_quantity
            c_s = min(remaining["store"], proj_store)
            proj_store -= c_s
            remaining["store"] -= c_s
            c_w = min(remaining["warehouse"], proj_wh)
            proj_wh -= c_w
            remaining["warehouse"] -= c_w
            results.append({
                "product_code":               lot.product.product_code,
                "name":                       lot.product.name,
                "expiry_date":                lot.expiry_date,
                "projected_store_quantity":   proj_store,
                "projected_warehouse_quantity": proj_wh,
            })
        if remaining["store"] > 0 or remaining["warehouse"] > 0:
            results.append({
                "product_code":     product_code,
                "name":             lots[0].product.name,
                "shortage":         True,
                "shortage_store":   remaining["store"],
                "shortage_warehouse": remaining["warehouse"],
            })
    return results


def stock_projection_view(request):
    target_date_str = request.GET.get("target_date")
    target_date = None
    projections = None
    if target_date_str:
        try:
            target_date  = datetime.date.fromisoformat(target_date_str)
            projections  = _project_stock(target_date)
        except ValueError:
            pass
    return render(request, "stock/stock_projection.html", {
        "target_date": target_date_str or "",
        "projections": projections,
    })


# ── 商品コード検索API（DB版） ─────────────────────────────────────────────────
def product_lookup_api(request, product_code):
    try:
        product = Product.objects.select_related("category").get(product_code=product_code)
    except Product.DoesNotExist:
        return JsonResponse({"error": "not_found"}, status=404)

    lots = StockLot.objects.filter(product=product)
    store_total = sum(lot.store_quantity for lot in lots)
    wh_total    = sum(lot.warehouse_quantity for lot in lots)

    return JsonResponse({
        "product_code":   product.product_code,
        "jan_code":       product.jan_code,
        "name":           product.name,
        "category":       product.category.name,
        "shelf_life_days": product.shelf_life_days,
        "mall_limit_days": product.mall_limit_days,
        "store_quantity":  store_total,
        "warehouse_quantity": wh_total,
        "total_quantity":  store_total + wh_total,
    })


# ── マスタ管理（DB版） ────────────────────────────────────────────────────────
def master_view(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    products   = Product.objects.select_related("category").order_by("product_code")
    categories = Category.objects.order_by("code")
    users      = User.objects.all()
    return render(request, "stock/master.html", {
        "products":   products,
        "categories": categories,
        "users":      users,
    })


# ── 履歴照会（入庫はダミー、出庫はShipmentPlan） ─────────────────────────────
def _filter_ship_qs(qs, date_mode, params):
    """ShipmentPlan QuerySet を日付条件で絞る"""
    try:
        if date_mode == "single":
            d = params.get("single_date", "")
            if d:
                qs = qs.filter(ship_date=datetime.date.fromisoformat(d))
        else:
            df = params.get("date_from", "")
            dt = params.get("date_to", "")
            if df:
                qs = qs.filter(ship_date__gte=datetime.date.fromisoformat(df))
            if dt:
                qs = qs.filter(ship_date__lte=datetime.date.fromisoformat(dt))
    except ValueError:
        pass
    return qs


def _confirm_plans(qs):
    """仮データをFEFO在庫反映して確定する。(shortage_msgs, confirmed_count) を返す"""
    plan_list = list(qs.select_related("product"))
    if not plan_list:
        return [], 0

    with transaction.atomic():
        totals = defaultdict(lambda: {"store": 0, "warehouse": 0})
        for plan in plan_list:
            totals[plan.product.product_code][plan.location] += plan.quantity

        shortage_msgs = []
        for product_code, amounts in totals.items():
            lots = StockLot.objects.filter(
                product__product_code=product_code
            ).order_by("expiry_date")
            remaining = {"store": amounts["store"], "warehouse": amounts["warehouse"]}
            for lot in lots:
                c_s = min(remaining["store"], max(0, lot.store_quantity))
                lot.store_quantity -= c_s
                remaining["store"] -= c_s
                c_w = min(remaining["warehouse"], max(0, lot.warehouse_quantity))
                lot.warehouse_quantity -= c_w
                remaining["warehouse"] -= c_w
                lot.save()
            if remaining["store"] > 0 or remaining["warehouse"] > 0:
                shortage_msgs.append(
                    f"{product_code}：在庫不足（店頭 {remaining['store']}個 / 倉庫 {remaining['warehouse']}個）"
                )

        qs.update(is_confirmed=True, confirmed_at=datetime.datetime.now())

    return shortage_msgs, len(plan_list)


def _apply_date_filter_receive(records, date_from, date_to):
    try:
        if date_from:
            df = datetime.date.fromisoformat(date_from)
            records = [r for r in records if r["received_at"] >= df]
        if date_to:
            dt = datetime.date.fromisoformat(date_to)
            records = [r for r in records if r["received_at"] <= dt]
    except ValueError:
        pass
    return records


def history_view(request):
    tab = request.GET.get("tab", "receive")

    # タブごとに独立したフィルターパラメータ（r_=入庫、s_=出庫）
    r_from = request.GET.get("r_from", "")
    r_to   = request.GET.get("r_to",   "")
    r_code = request.GET.get("r_code", "").strip()
    r_searched = bool(r_from or r_to or r_code)

    s_from = request.GET.get("s_from", "")
    s_to   = request.GET.get("s_to",   "")
    s_code = request.GET.get("s_code", "").strip()
    s_searched = bool(s_from or s_to or s_code)

    # ── POST：出庫タブの削除・確定アクション ──────────────────────────────────
    if request.method == "POST":
        action = request.POST.get("action", "")
        # 出庫フィルター
        sf = request.POST.get("s_from", "").strip()
        st = request.POST.get("s_to",   "").strip()
        sc = request.POST.get("s_code", "").strip()
        # 入庫フィルターを保持
        rf = request.POST.get("r_from", "").strip()
        rt = request.POST.get("r_to",   "").strip()
        rc = request.POST.get("r_code", "").strip()

        target = ShipmentPlan.objects.filter(is_confirmed=False)
        try:
            if sf: target = target.filter(ship_date__gte=datetime.date.fromisoformat(sf))
            if st: target = target.filter(ship_date__lte=datetime.date.fromisoformat(st))
        except ValueError:
            pass
        if sc:
            target = target.filter(product__product_code=sc)

        if action == "delete":
            count = target.count()
            target.delete()
            messages.success(request, f"{count}件の仮データを削除しました。")
        elif action == "confirm":
            shortage_msgs, count = _confirm_plans(target)
            if count:
                messages.success(request, f"{count}件を確定し、在庫に反映しました。")
            else:
                messages.warning(request, "確定する仮データがありませんでした。")
            for msg in shortage_msgs:
                messages.warning(request, msg)

        # PRG：両タブのパラメータを保持してリダイレクト
        params = {"tab": "ship"}
        if sf: params["s_from"] = sf
        if st: params["s_to"]   = st
        if sc: params["s_code"] = sc
        if rf: params["r_from"] = rf
        if rt: params["r_to"]   = rt
        if rc: params["r_code"] = rc
        return redirect(f"{request.path}?{urlencode(params)}")

    # ── GET：入庫履歴を取得 ───────────────────────────────────────────────────
    receive_records = []
    if r_searched:
        result = _apply_date_filter_receive(list(DUMMY_RECEIVE_HISTORY), r_from, r_to)
        if r_code:
            result = [r for r in result if r["product_code"] == r_code]
        receive_records = result

    # ── GET：出庫履歴を取得 ───────────────────────────────────────────────────
    ship_records      = []
    ship_total        = 0
    unconfirmed_count = 0
    confirmed_count   = 0
    if s_searched:
        qs = ShipmentPlan.objects.select_related("product__category").order_by("ship_date", "id")
        try:
            if s_from: qs = qs.filter(ship_date__gte=datetime.date.fromisoformat(s_from))
            if s_to:   qs = qs.filter(ship_date__lte=datetime.date.fromisoformat(s_to))
        except ValueError:
            pass
        if s_code:
            qs = qs.filter(product__product_code=s_code)
        ship_records = [{
            "ship_date":    r.ship_date,
            "product_code": r.product.product_code,
            "jan_code":     r.product.jan_code,
            "name":         r.product.name,
            "category":     r.product.category.name,
            "location":     r.location,
            "quantity":     r.quantity,
            "remarks":      r.remarks,
            "is_confirmed": r.is_confirmed,
        } for r in qs]
        ship_total        = sum(r["quantity"] for r in ship_records)
        unconfirmed_count = sum(1 for r in ship_records if not r["is_confirmed"])
        confirmed_count   = len(ship_records) - unconfirmed_count

    # リセットリンク（相手タブのパラメータを保持）
    r_reset = urlencode({"tab": "receive",
                         **({} if not s_from else {"s_from": s_from}),
                         **({} if not s_to   else {"s_to":   s_to}),
                         **({} if not s_code else {"s_code": s_code})})
    s_reset = urlencode({"tab": "ship",
                         **({} if not r_from else {"r_from": r_from}),
                         **({} if not r_to   else {"r_to":   r_to}),
                         **({} if not r_code else {"r_code": r_code})})

    return render(request, "stock/history.html", {
        "tab": tab,
        # 入庫
        "r_from": r_from, "r_to": r_to, "r_code": r_code,
        "r_searched": r_searched, "receive_records": receive_records,
        "r_reset": r_reset,
        # 出庫
        "s_from": s_from, "s_to": s_to, "s_code": s_code,
        "s_searched": s_searched, "ship_records": ship_records,
        "ship_total": ship_total,
        "s_reset": s_reset,
        "unconfirmed_count": unconfirmed_count,
        "confirmed_count":   confirmed_count,
        "query_string": request.GET.urlencode(),
    })


def history_csv_view(request):
    tab = request.GET.get("tab", "receive")

    if tab == "receive":
        r_from = request.GET.get("r_from", "")
        r_to   = request.GET.get("r_to",   "")
        r_code = request.GET.get("r_code", "").strip()
        records = _apply_date_filter_receive(list(DUMMY_RECEIVE_HISTORY), r_from, r_to)
        if r_code:
            records = [r for r in records if r["product_code"] == r_code]
        filename = "入庫履歴.csv"
        headers  = ["入荷日", "商品コード", "JANコード", "商品名", "カテゴリ", "賞味期限", "入庫先", "入庫数", "備考"]
        rows = [[
            r["received_at"].strftime("%Y/%m/%d"),
            r["product_code"], r["jan_code"], r["name"], r["category"],
            r["expiry_date"].strftime("%Y/%m/%d"),
            "店頭" if r["location"] == "store" else "倉庫",
            r["quantity"], r["remarks"],
        ] for r in records]
    else:
        s_from = request.GET.get("s_from", "")
        s_to   = request.GET.get("s_to",   "")
        s_code = request.GET.get("s_code", "").strip()
        qs = ShipmentPlan.objects.select_related("product__category").order_by("ship_date")
        try:
            if s_from: qs = qs.filter(ship_date__gte=datetime.date.fromisoformat(s_from))
            if s_to:   qs = qs.filter(ship_date__lte=datetime.date.fromisoformat(s_to))
        except ValueError:
            pass
        if s_code:
            qs = qs.filter(product__product_code=s_code)
        filename = "出庫履歴.csv"
        headers  = ["出荷日", "商品コード", "JANコード", "商品名", "カテゴリ", "出荷元", "出荷数", "備考", "確定状態"]
        rows = [[
            r.ship_date.strftime("%Y/%m/%d"),
            r.product.product_code, r.product.jan_code, r.product.name, r.product.category.name,
            "店頭" if r.location == "store" else "倉庫",
            r.quantity, r.remarks,
            "確定" if r.is_confirmed else "仮",
        ] for r in qs]

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response
