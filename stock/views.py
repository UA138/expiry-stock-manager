import csv
import datetime
from collections import defaultdict
from urllib.parse import quote, urlencode

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
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




# ── 認証 ─────────────────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect("stock:stock_list")

    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next") or request.POST.get("next") or "stock:stock_list"
            return redirect(next_url)
        error = "ユーザーIDまたはパスワードが正しくありません。"

    return render(request, "stock/login.html", {
        "error": error,
        "next": request.GET.get("next", ""),
    })


def logout_view(request):
    logout(request)
    return redirect("stock:login")


# ── 在庫一覧（DB版） ──────────────────────────────────────────────────────────
@login_required
def stock_list_view(request):
    from django.db.models import Q

    q        = request.GET.get("q",        "").strip()
    category = request.GET.get("category", "")
    status_f = request.GET.get("status",   "")

    # 全ロットから商品別の合計を計算（フィルターに関係なく常に全体合計を表示）
    all_lots = StockLot.objects.select_related("product__category")
    product_totals = defaultdict(lambda: {"store": 0, "warehouse": 0})
    for lot in all_lots:
        t = product_totals[lot.product.product_code]
        t["store"]     += lot.store_quantity
        t["warehouse"] += lot.warehouse_quantity

    # 絞り込み（キーワード・カテゴリはDB側で処理）
    qs = all_lots.order_by("product__product_code", "expiry_date")
    if q:
        qs = qs.filter(
            Q(product__product_code__icontains=q) |
            Q(product__jan_code__icontains=q) |
            Q(product__name__icontains=q)
        )
    if category:
        qs = qs.filter(product__category__code=category)

    stocks = []
    for lot in qs:
        status      = _expiry_status(lot.expiry_date)
        mall_status = _mall_status(lot.expiry_date, lot.product.mall_limit_days)
        if status_f:
            if status_f in ("expired", "warning", "ok") and status != status_f:
                continue
            if status_f in ("mall_ng", "mall_warning") and mall_status != status_f:
                continue
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
            "status":             status,
            "mall_status":        mall_status,
        })

    return render(request, "stock/stock_list.html", {
        "stocks":     stocks,
        "categories": Category.objects.order_by("code"),
        "q":          q,
        "category":   category,
        "status_f":   status_f,
        "user_role":  _get_user_role(request.user),
    })


# ── 在庫ロット編集（DB版） ─────────────────────────────────────────────────────

@login_required
def stock_edit_view(request, pk):
    if _is_viewer(request.user):
        messages.warning(request, "閲覧者は在庫の編集ができません。")
        return redirect("stock:stock_list")
    try:
        lot = StockLot.objects.select_related("product__category").get(pk=pk)
    except StockLot.DoesNotExist:
        messages.warning(request, "該当するロットが見つかりませんでした。")
        return redirect("stock:stock_list")

    def _lot_context(store_quantity, wh_quantity, expiry_date):
        return {
            "id":                 lot.id,
            "product_code":       lot.product.product_code,
            "jan_code":           lot.product.jan_code,
            "name":               lot.product.name,
            "category":           lot.product.category.name,
            "store_quantity":     store_quantity,
            "warehouse_quantity": wh_quantity,
            "expiry_date":        expiry_date,
        }

    if request.method == "POST":
        expiry_str = request.POST.get("expiry_date", "").strip()
        store_str  = request.POST.get("store_quantity", "").strip()
        wh_str     = request.POST.get("warehouse_quantity", "").strip()

        errors = []
        expiry_date    = lot.expiry_date
        store_quantity = lot.store_quantity
        wh_quantity    = lot.warehouse_quantity

        if not expiry_str:
            errors.append("賞味期限は必須です。")
        else:
            try:
                expiry_date = datetime.date.fromisoformat(expiry_str)
            except ValueError:
                errors.append("賞味期限の形式が正しくありません。")

        try:
            store_quantity = int(store_str) if store_str else 0
        except ValueError:
            errors.append("店頭在庫数は整数で入力してください。")

        try:
            wh_quantity = int(wh_str) if wh_str else 0
        except ValueError:
            errors.append("倉庫在庫数は整数で入力してください。")

        if not errors:
            lot.expiry_date        = expiry_date
            lot.store_quantity     = store_quantity
            lot.warehouse_quantity = wh_quantity
            lot.save()
            messages.success(request, f"{lot.product.name}（賞味期限: {expiry_date}）のロットを更新しました。")
            return redirect("stock:stock_list")

        return render(request, "stock/stock_form.html", {
            "mode":   "edit",
            "errors": errors,
            "item":   _lot_context(store_quantity, wh_quantity, expiry_date),
        })

    return render(request, "stock/stock_form.html", {
        "mode": "edit",
        "item": _lot_context(lot.store_quantity, lot.warehouse_quantity, lot.expiry_date),
    })


# ── 在庫ロット削除 ────────────────────────────────────────────────────────────
@login_required
def stock_delete_view(request, pk):
    if request.method != "POST":
        return redirect("stock:stock_list")
    if _is_viewer(request.user):
        messages.warning(request, "閲覧者は在庫の削除ができません。")
        return redirect("stock:stock_list")
    try:
        lot = StockLot.objects.select_related("product").get(pk=pk)
    except StockLot.DoesNotExist:
        messages.warning(request, "該当するロットが見つかりませんでした。")
        return redirect("stock:stock_list")
    name = lot.product.name
    expiry = lot.expiry_date
    lot.delete()
    messages.success(request, f"{name}（賞味期限: {expiry}）のロットを削除しました。")
    return redirect("stock:stock_list")


# ── 棚卸し（DB版） ────────────────────────────────────────────────────────────
@login_required
def stocktake_view(request):
    if request.method == "POST":
        if _is_viewer(request.user):
            messages.warning(request, "閲覧者は棚卸しデータを保存できません。")
            return redirect("stock:stocktake")
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
    return render(request, "stock/stocktake.html", {
        "stocks":    stocks,
        "user_role": _get_user_role(request.user),
    })


# ── 入庫登録（POST保存は後でDB連携） ─────────────────────────────────────────
@login_required
def stock_receive_view(request):
    if request.method == "POST":
        messages.success(request, "入庫登録が完了しました。")
        return redirect("stock:stock_receive")
    return render(request, "stock/stock_receive.html")


# ── 入出庫登録（タブ統合版） ──────────────────────────────────────────────────
def inout_view(request):
    tab = request.GET.get("tab", "receive")

    if request.method == "POST":
        if _is_viewer(request.user):
            messages.warning(request, "閲覧者は入出庫の登録ができません。")
            return redirect(f"{request.path}?tab={request.POST.get('tab', 'receive')}")
        tab_post = request.POST.get("tab", "receive")

        if tab_post == "receive":
            received_at_str = request.POST.get("received_at", "").strip()
            try:
                received_at = datetime.date.fromisoformat(received_at_str) if received_at_str else datetime.date.today()
            except ValueError:
                received_at = datetime.date.today()

            row_indices = sorted({
                key.split("_")[-1]
                for key in request.POST.keys()
                if key.startswith("product_code_")
            }, key=lambda x: int(x) if x.isdigit() else 0)

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

                expiry_str = request.POST.get(f"expiry_date_{idx}", "").strip()
                if not expiry_str:
                    errors.append(f"商品コード「{product_code}」：賞味期限が未入力です")
                    continue
                try:
                    expiry_date = datetime.date.fromisoformat(expiry_str)
                except ValueError:
                    errors.append(f"商品コード「{product_code}」：賞味期限の形式が不正です")
                    continue

                qty_str = request.POST.get(f"quantity_{idx}", "").strip()
                if not qty_str:
                    errors.append(f"商品コード「{product_code}」：入庫数が未入力です")
                    continue
                try:
                    quantity = int(qty_str)
                except ValueError:
                    errors.append(f"商品コード「{product_code}」：入庫数は整数で入力してください")
                    continue

                location = request.POST.get(f"location_{idx}", "store")
                remarks  = request.POST.get(f"remarks_{idx}", "")[:30]

                ReceiveHistory.objects.create(
                    product=product,
                    received_at=received_at,
                    expiry_date=expiry_date,
                    location=location,
                    quantity=quantity,
                    remarks=remarks,
                    is_confirmed=False,
                )
                registered += 1

            if registered > 0:
                messages.success(request, f"{registered}件の入庫予定を登録しました（仮データ）。履歴照会から確定してください。")
            for err in errors:
                messages.warning(request, err)
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

    return render(request, "stock/stock_inout.html", {
        "tab":       tab,
        "user_role": _get_user_role(request.user),
    })


# ── 出庫登録（DB版：ShipmentPlan に仮データとして保存） ───────────────────────
@login_required
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
@login_required
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
        if _is_viewer(request.user):
            messages.warning(request, "閲覧者はこの操作ができません。")
            return redirect(request.path)
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
        "user_role": _get_user_role(request.user),
    })


# ── 在庫照会（DB版：ShipmentPlan でFEFO計算） ────────────────────────────────
def _expiry_status_at(expiry_date, reference_date):
    days_left = (expiry_date - reference_date).days
    if days_left < 0:
        return "expired"
    if days_left <= 3:
        return "warning"
    return "ok"


def _mall_status_at(expiry_date, mall_limit_days, reference_date):
    if mall_limit_days is None:
        return "mall_ok"
    days_left = (expiry_date - reference_date).days
    if days_left <= mall_limit_days:
        return "mall_ng"
    if days_left <= mall_limit_days + 5:
        return "mall_warning"
    return "mall_ok"


def _project_stock(target_date):
    # 未確定出庫予定のみ（確定済みはすでにStockLotに反映済み）
    plans = ShipmentPlan.objects.filter(
        ship_date__lte=target_date,
        is_confirmed=False,
    ).select_related("product")

    shipments_by_product = defaultdict(lambda: {"store": 0, "warehouse": 0})
    for plan in plans:
        shipments_by_product[plan.product.product_code][plan.location] += plan.quantity

    # 未確定入庫予定（received_at <= target_date のもの）
    planned_receives = ReceiveHistory.objects.filter(
        is_confirmed=False,
        received_at__lte=target_date,
    ).select_related("product__category")

    receive_adds = {}
    for r in planned_receives:
        key = (r.product.product_code, r.expiry_date)
        if key not in receive_adds:
            receive_adds[key] = {
                "store": 0, "warehouse": 0,
                "name": r.product.name,
                "category_name": r.product.category.name,
                "category_code": r.product.category.code,
                "mall_limit_days": r.product.mall_limit_days,
            }
        receive_adds[key][r.location] += r.quantity

    # 現在のStockLotに仮入庫を加算してロットを構築
    lots_by_product = defaultdict(list)
    seen_keys = set()
    for lot in StockLot.objects.select_related("product__category").order_by("expiry_date"):
        key = (lot.product.product_code, lot.expiry_date)
        seen_keys.add(key)
        add = receive_adds.get(key, {})
        lots_by_product[lot.product.product_code].append({
            "product_code":       lot.product.product_code,
            "name":               lot.product.name,
            "category_name":      lot.product.category.name,
            "category_code":      lot.product.category.code,
            "expiry_date":        lot.expiry_date,
            "mall_limit_days":    lot.product.mall_limit_days,
            "store_quantity":     lot.store_quantity     + add.get("store", 0),
            "warehouse_quantity": lot.warehouse_quantity + add.get("warehouse", 0),
        })

    # StockLotにまだ存在しない新規ロット（仮入庫のみ）
    for key, data in receive_adds.items():
        if key in seen_keys:
            continue
        lots_by_product[key[0]].append({
            "product_code":       key[0],
            "name":               data["name"],
            "category_name":      data["category_name"],
            "category_code":      data["category_code"],
            "expiry_date":        key[1],
            "mall_limit_days":    data["mall_limit_days"],
            "store_quantity":     data["store"],
            "warehouse_quantity": data["warehouse"],
        })

    # ロットを賞味期限順に並べ直す
    for pc in lots_by_product:
        lots_by_product[pc].sort(key=lambda x: x["expiry_date"])

    # FEFO出庫シミュレーション
    results = []
    for product_code, lots in lots_by_product.items():
        remaining = dict(shipments_by_product.get(product_code, {"store": 0, "warehouse": 0}))
        for lot in lots:
            proj_store = lot["store_quantity"]
            proj_wh    = lot["warehouse_quantity"]
            c_s = min(remaining["store"], proj_store)
            proj_store -= c_s
            remaining["store"] -= c_s
            c_w = min(remaining["warehouse"], proj_wh)
            proj_wh -= c_w
            remaining["warehouse"] -= c_w
            results.append({
                "product_code":    lot["product_code"],
                "name":            lot["name"],
                "category_name":   lot["category_name"],
                "category_code":   lot["category_code"],
                "expiry_date":     lot["expiry_date"],
                "status":          _expiry_status_at(lot["expiry_date"], target_date),
                "mall_status":     _mall_status_at(lot["expiry_date"], lot["mall_limit_days"], target_date),
                "projected_total": proj_store + proj_wh,
            })
        if remaining["store"] > 0 or remaining["warehouse"] > 0:
            results.append({
                "product_code":  product_code,
                "name":          lots[0]["name"] if lots else "",
                "category_name": lots[0]["category_name"] if lots else "",
                "category_code": lots[0]["category_code"] if lots else "",
                "shortage":      True,
                "shortage_total": remaining["store"] + remaining["warehouse"],
            })
    return results


@login_required
def stock_projection_view(request):
    target_date_str = request.GET.get("target_date", "")
    keyword   = request.GET.get("keyword", "").strip()
    category  = request.GET.get("category", "").strip()
    status_f  = request.GET.get("status_filter", "")

    target_date = None
    projections = None
    if target_date_str:
        try:
            target_date = datetime.date.fromisoformat(target_date_str)
            projections = _project_stock(target_date)

            if keyword:
                projections = [r for r in projections
                               if keyword in r.get("name", "") or keyword in r.get("product_code", "")]
            if category:
                projections = [r for r in projections if r.get("category_code") == category]
            if status_f:
                projections = [r for r in projections
                               if r.get("shortage") or r.get("status") == status_f]
        except ValueError:
            pass

    return render(request, "stock/stock_projection.html", {
        "target_date":  target_date_str,
        "projections":  projections,
        "keyword":      keyword,
        "category":     category,
        "status_f":     status_f,
        "categories":   Category.objects.order_by("code"),
    })


# ── 商品コード検索API（DB版） ─────────────────────────────────────────────────
@login_required
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


# ── マスタ管理 CSV ────────────────────────────────────────────────────────────
def _master_product_csv():
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote('商品マスタ.csv')}"
    writer = csv.writer(response)
    writer.writerow(["商品コード", "JANコード", "商品名", "カテゴリ", "賞味期限（製造より○日）", "モール期限（残○日まで）"])
    for p in Product.objects.select_related("category").order_by("product_code"):
        writer.writerow([
            p.product_code, p.jan_code, p.name, p.category.name,
            p.shelf_life_days if p.shelf_life_days is not None else "",
            p.mall_limit_days if p.mall_limit_days is not None else "",
        ])
    return response


def _master_category_csv():
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote('カテゴリマスタ.csv')}"
    writer = csv.writer(response)
    writer.writerow(["カテゴリコード", "カテゴリ名"])
    for c in Category.objects.order_by("code"):
        writer.writerow([c.code, c.name])
    return response


def _master_user_csv(User):
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote('ユーザーマスタ.csv')}"
    writer = csv.writer(response)
    writer.writerow(["ユーザーID", "権限"])
    for u in User.objects.order_by("username"):
        try:
            role = u.profile.get_role_display()
        except Exception:
            role = "未設定"
        writer.writerow([u.username, role])
    return response


def _get_user_role(user):
    """ユーザーの権限ロール文字列を返す。スーパーユーザーは常に admin 扱い。"""
    if user.is_superuser:
        return "admin"
    try:
        return user.profile.role
    except Exception:
        return "staff"


def _is_viewer(user):
    return _get_user_role(user) == "viewer"


def _notify_admin_new_user(username):
    """新規ユーザー登録を管理者にメール通知する。失敗しても登録処理は継続する。"""
    from django.conf import settings
    from django.core.mail import send_mail

    notify_email = getattr(settings, 'ADMIN_NOTIFY_EMAIL', '').strip()
    if not notify_email:
        return

    recipients = [e.strip() for e in notify_email.split(',') if e.strip()]
    if not recipients:
        return

    try:
        send_mail(
            subject='【在庫管理システム】新規ユーザーが登録されました',
            message=(
                f'新規ユーザーが自己登録しました。\n\n'
                f'ユーザーID：{username}\n'
                f'現在の権限：閲覧者\n\n'
                f'マスタ管理 > ユーザータブから権限を変更できます。\n'
                f'（担当者に変更するか、閲覧者のままにするかご判断ください）'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        pass


# ── マスタ管理（CRUD + CSV） ──────────────────────────────────────────────────
@login_required
def master_view(request):
    from django.contrib.auth import get_user_model
    from .models import UserProfile
    User = get_user_model()

    role = _get_user_role(request.user)

    # 閲覧者はアクセス不可
    if role == "viewer":
        return render(request, "stock/master.html", {"access_denied": True})

    tab = request.GET.get("tab", "product")

    # CSV ダウンロード
    csv_type = request.GET.get("csv", "")
    if csv_type == "product":
        return _master_product_csv()
    if csv_type == "category":
        return _master_category_csv()
    if csv_type == "user":
        return _master_user_csv(User)

    if request.method == "POST":
        action = request.POST.get("action", "")
        redirect_tab = "product"

        # ── 商品追加・編集：担当者以上 ────────────────────────────────────────
        if action == "add_product":
            redirect_tab = "product"
            code      = request.POST.get("product_code", "").strip()
            jan       = request.POST.get("jan_code", "").strip()
            name      = request.POST.get("name", "").strip()
            cat_id    = request.POST.get("category_id", "").strip()
            shelf_str = request.POST.get("shelf_life_days", "").strip()
            mall_str  = request.POST.get("mall_limit_days", "").strip()
            errors = []
            if not code: errors.append("商品コードは必須です。")
            if not name: errors.append("商品名は必須です。")
            if code and Product.objects.filter(product_code=code).exists():
                errors.append(f"商品コード「{code}」はすでに使用されています。")
            category = None
            if cat_id:
                try:
                    category = Category.objects.get(id=cat_id)
                except Category.DoesNotExist:
                    errors.append("選択されたカテゴリが存在しません。")
            else:
                errors.append("カテゴリを選択してください。")
            shelf = mall = None
            if shelf_str:
                try: shelf = int(shelf_str)
                except ValueError: errors.append("賞味期限日数は整数で入力してください。")
            if mall_str:
                try: mall = int(mall_str)
                except ValueError: errors.append("モール期限日数は整数で入力してください。")
            if not errors:
                Product.objects.create(
                    product_code=code, jan_code=jan, name=name,
                    category=category, shelf_life_days=shelf, mall_limit_days=mall,
                )
                messages.success(request, f"商品「{name}」を追加しました。")
            else:
                for e in errors: messages.warning(request, e)

        elif action == "edit_product":
            redirect_tab = "product"
            pk = request.POST.get("product_id", "")
            try:
                product = Product.objects.get(pk=pk)
            except Product.DoesNotExist:
                messages.warning(request, "商品が見つかりません。")
            else:
                code      = request.POST.get("product_code", "").strip()
                jan       = request.POST.get("jan_code", "").strip()
                name      = request.POST.get("name", "").strip()
                cat_id    = request.POST.get("category_id", "").strip()
                shelf_str = request.POST.get("shelf_life_days", "").strip()
                mall_str  = request.POST.get("mall_limit_days", "").strip()
                errors = []
                if not code: errors.append("商品コードは必須です。")
                if not name: errors.append("商品名は必須です。")
                if code and Product.objects.filter(product_code=code).exclude(pk=pk).exists():
                    errors.append(f"商品コード「{code}」はすでに使用されています。")
                category = None
                if cat_id:
                    try:
                        category = Category.objects.get(id=cat_id)
                    except Category.DoesNotExist:
                        errors.append("選択されたカテゴリが存在しません。")
                else:
                    errors.append("カテゴリを選択してください。")
                shelf = mall = None
                if shelf_str:
                    try: shelf = int(shelf_str)
                    except ValueError: errors.append("賞味期限日数は整数で入力してください。")
                if mall_str:
                    try: mall = int(mall_str)
                    except ValueError: errors.append("モール期限日数は整数で入力してください。")
                if not errors:
                    product.product_code    = code
                    product.jan_code        = jan
                    product.name            = name
                    product.category        = category
                    product.shelf_life_days = shelf
                    product.mall_limit_days = mall
                    product.save()
                    messages.success(request, f"商品「{name}」を更新しました。")
                else:
                    for e in errors: messages.warning(request, e)

        # ── 商品削除：担当者以上 ──────────────────────────────────────────────
        elif action == "delete_product":
            redirect_tab = "product"
            pk = request.POST.get("product_id", "")
            try:
                product = Product.objects.get(pk=pk)
                pname = product.name
                product.delete()
                messages.success(request, f"商品「{pname}」を削除しました。")
            except Product.DoesNotExist:
                messages.warning(request, "商品が見つかりません。")
            except Exception:
                messages.warning(request, "この商品は在庫データに紐づいているため削除できません。")

        elif action == "add_category":
            redirect_tab = "category"
            if role != "admin":
                messages.warning(request, "カテゴリの追加は管理者権限が必要です。")
            else:
                code = request.POST.get("code", "").strip()
                name = request.POST.get("name", "").strip()
                errors = []
                if not code: errors.append("カテゴリコードは必須です。")
                if not name: errors.append("カテゴリ名は必須です。")
                if code and Category.objects.filter(code=code).exists():
                    errors.append(f"カテゴリコード「{code}」はすでに使用されています。")
                if name and Category.objects.filter(name=name).exists():
                    errors.append(f"カテゴリ名「{name}」はすでに使用されています。")
                if not errors:
                    Category.objects.create(code=code, name=name)
                    messages.success(request, f"カテゴリ「{name}」を追加しました。")
                else:
                    for e in errors: messages.warning(request, e)

        elif action == "edit_category":
            redirect_tab = "category"
            if role != "admin":
                messages.warning(request, "カテゴリの編集は管理者権限が必要です。")
            else:
                pk = request.POST.get("category_id", "")
                try:
                    category = Category.objects.get(pk=pk)
                except Category.DoesNotExist:
                    messages.warning(request, "カテゴリが見つかりません。")
                else:
                    code = request.POST.get("code", "").strip()
                    name = request.POST.get("name", "").strip()
                    errors = []
                    if not code: errors.append("カテゴリコードは必須です。")
                    if not name: errors.append("カテゴリ名は必須です。")
                    if code and Category.objects.filter(code=code).exclude(pk=pk).exists():
                        errors.append(f"カテゴリコード「{code}」はすでに使用されています。")
                    if name and Category.objects.filter(name=name).exclude(pk=pk).exists():
                        errors.append(f"カテゴリ名「{name}」はすでに使用されています。")
                    if not errors:
                        category.code = code
                        category.name = name
                        category.save()
                        messages.success(request, f"カテゴリ「{name}」を更新しました。")
                    else:
                        for e in errors: messages.warning(request, e)

        elif action == "delete_category":
            redirect_tab = "category"
            if role != "admin":
                messages.warning(request, "カテゴリの削除は管理者権限が必要です。")
            else:
                pk = request.POST.get("category_id", "")
                try:
                    category = Category.objects.get(pk=pk)
                    cname = category.name
                    category.delete()
                    messages.success(request, f"カテゴリ「{cname}」を削除しました。")
                except Category.DoesNotExist:
                    messages.warning(request, "カテゴリが見つかりません。")
                except Exception:
                    messages.warning(request, "このカテゴリは商品に紐づいているため削除できません。")

        # ── ユーザー追加・削除：管理者のみ ────────────────────────────────────
        elif action == "add_user":
            redirect_tab = "user"
            if role != "admin":
                messages.warning(request, "ユーザー追加は管理者権限が必要です。")
            else:
                username = request.POST.get("username", "").strip()
                password = request.POST.get("password", "")
                new_role = request.POST.get("role", "staff")
                errors   = []
                if not username: errors.append("ユーザーIDは必須です。")
                if not password: errors.append("パスワードは必須です。")
                if username and User.objects.filter(username=username).exists():
                    errors.append(f"ユーザーID「{username}」はすでに使用されています。")
                if not errors:
                    new_user = User.objects.create_user(username=username, password=password)
                    UserProfile.objects.create(user=new_user, role=new_role)
                    messages.success(request, f"ユーザー「{username}」を追加しました。")
                else:
                    for e in errors: messages.warning(request, e)

        # ── ユーザー編集：管理者（全員）、担当者（自分のみ・権限変更不可） ─────
        elif action == "edit_user":
            redirect_tab = "user"
            pk = request.POST.get("user_id", "")
            if role == "staff" and str(request.user.pk) != str(pk):
                messages.warning(request, "自分以外のユーザー情報は編集できません。")
            else:
                try:
                    target_user = User.objects.get(pk=pk)
                except User.DoesNotExist:
                    messages.warning(request, "ユーザーが見つかりません。")
                else:
                    username     = request.POST.get("username", "").strip()
                    new_password = request.POST.get("new_password", "")
                    errors = []
                    if not username: errors.append("ユーザーIDは必須です。")
                    if username and User.objects.filter(username=username).exclude(pk=pk).exists():
                        errors.append(f"ユーザーID「{username}」はすでに使用されています。")
                    if not errors:
                        target_user.username = username
                        if new_password:
                            target_user.set_password(new_password)
                        target_user.save()
                        profile, _ = UserProfile.objects.get_or_create(user=target_user)
                        # 管理者のみ権限変更可
                        if role == "admin":
                            profile.role = request.POST.get("role", profile.role)
                        profile.save()
                        messages.success(request, f"ユーザー「{username}」を更新しました。")
                    else:
                        for e in errors: messages.warning(request, e)

        elif action == "delete_user":
            redirect_tab = "user"
            if role != "admin":
                messages.warning(request, "ユーザーの削除は管理者権限が必要です。")
            else:
                pk = request.POST.get("user_id", "")
                if str(request.user.pk) == str(pk):
                    messages.warning(request, "自分自身は削除できません。")
                else:
                    try:
                        target_user = User.objects.get(pk=pk)
                        uname = target_user.username
                        target_user.delete()
                        messages.success(request, f"ユーザー「{uname}」を削除しました。")
                    except User.DoesNotExist:
                        messages.warning(request, "ユーザーが見つかりません。")

        return redirect(f"{request.path}?tab={redirect_tab}")

    # GET
    products   = Product.objects.select_related("category").order_by("product_code")
    categories = Category.objects.order_by("code")

    user_list = []
    for u in User.objects.order_by("username"):
        try:
            u_role         = u.profile.role
            u_role_display = u.profile.get_role_display()
        except Exception:
            u_role         = "admin" if u.is_superuser else "staff"
            u_role_display = "管理者" if u.is_superuser else "担当者"
        user_list.append({
            "id":           u.id,
            "username":     u.username,
            "role":         u_role,
            "role_display": u_role_display,
            "is_self":      u.id == request.user.id,
        })

    return render(request, "stock/master.html", {
        "products":   products,
        "categories": categories,
        "user_list":  user_list,
        "tab":        tab,
        "user_role":  role,
    })

# ── トップページ（ツール紹介・ログイン不要） ─────────────────────────────────
def landing_view(request):
    if request.user.is_authenticated:
        return redirect("stock:stock_list")
    return render(request, "stock/landing.html")


# ── ユーザー自己登録（ログイン不要） ──────────────────────────────────────────
def register_view(request):
    from django.contrib.auth import get_user_model
    from .models import UserProfile
    User = get_user_model()

    if request.user.is_authenticated:
        return redirect("stock:stock_list")

    errors = []
    username = password = ""
    if request.method == "POST":
        username  = request.POST.get("username", "").strip()
        password  = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        if not username: errors.append("ユーザーIDは必須です。")
        if not password: errors.append("パスワードは必須です。")
        if password and password != password2:
            errors.append("パスワードが一致しません。")
        if username and User.objects.filter(username=username).exists():
            errors.append(f"ユーザーID「{username}」はすでに使用されています。")

        if not errors:
            new_user = User.objects.create_user(username=username, password=password)
            UserProfile.objects.create(user=new_user, role="viewer")
            _notify_admin_new_user(username)
            login(request, new_user)
            return redirect("stock:stock_list")

    return render(request, "stock/register.html", {
        "errors":   errors,
        "username": username,
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


def _confirm_receives(qs):
    """仮入庫データをStockLotに反映して確定する。(confirmed_count, skipped_count) を返す"""
    today = datetime.date.today()
    all_records  = list(qs.filter(is_confirmed=False).select_related("product"))
    to_confirm   = [r for r in all_records if r.received_at <= today]
    skipped      = len(all_records) - len(to_confirm)
    if not to_confirm:
        return 0, skipped
    with transaction.atomic():
        for r in to_confirm:
            lot, _ = StockLot.objects.get_or_create(
                product=r.product,
                expiry_date=r.expiry_date,
                defaults={"store_quantity": 0, "warehouse_quantity": 0},
            )
            if r.location == "store":
                lot.store_quantity += r.quantity
            else:
                lot.warehouse_quantity += r.quantity
            lot.save()
            r.is_confirmed = True
            r.confirmed_at = datetime.datetime.now(datetime.timezone.utc)
            r.save()
    return len(to_confirm), skipped


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




@login_required
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

    # ── POST：入庫・出庫タブの削除・確定アクション ───────────────────────────
    if request.method == "POST":
        if _is_viewer(request.user):
            messages.warning(request, "閲覧者はこの操作ができません。")
            return redirect(f"{request.path}?{request.GET.urlencode()}")
        form_tab = request.POST.get("form_tab", "ship")
        action   = request.POST.get("action", "")
        rf = request.POST.get("r_from", "").strip()
        rt = request.POST.get("r_to",   "").strip()
        rc = request.POST.get("r_code", "").strip()
        sf = request.POST.get("s_from", "").strip()
        st = request.POST.get("s_to",   "").strip()
        sc = request.POST.get("s_code", "").strip()

        if form_tab == "receive":
            target = ReceiveHistory.objects.filter(is_confirmed=False)
            try:
                if rf: target = target.filter(received_at__gte=datetime.date.fromisoformat(rf))
                if rt: target = target.filter(received_at__lte=datetime.date.fromisoformat(rt))
            except ValueError:
                pass
            if rc:
                target = target.filter(product__product_code=rc)

            if action == "delete":
                count = target.count()
                target.delete()
                messages.success(request, f"{count}件の仮データを削除しました。")
            elif action == "confirm":
                count, skipped = _confirm_receives(target)
                if count:
                    messages.success(request, f"{count}件を確定し、在庫に反映しました。")
                if skipped:
                    messages.warning(request, f"{skipped}件は入荷日が未来のためスキップしました（仮データとして残ります）。")
                if not count and not skipped:
                    messages.warning(request, "確定する仮データがありませんでした。")

            params = {"tab": "receive"}
            if rf: params["r_from"] = rf
            if rt: params["r_to"]   = rt
            if rc: params["r_code"] = rc
            if sf: params["s_from"] = sf
            if st: params["s_to"]   = st
            if sc: params["s_code"] = sc
            return redirect(f"{request.path}?{urlencode(params)}")

        else:
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

            params = {"tab": "ship"}
            if sf: params["s_from"] = sf
            if st: params["s_to"]   = st
            if sc: params["s_code"] = sc
            if rf: params["r_from"] = rf
            if rt: params["r_to"]   = rt
            if rc: params["r_code"] = rc
            return redirect(f"{request.path}?{urlencode(params)}")

    # ── GET：入庫履歴を取得 ───────────────────────────────────────────────────
    receive_records    = []
    r_total_qty        = 0
    r_unconfirmed_count = 0
    r_confirmed_count  = 0
    if r_searched:
        rqs = ReceiveHistory.objects.select_related("product__category").order_by("received_at", "id")
        try:
            if r_from: rqs = rqs.filter(received_at__gte=datetime.date.fromisoformat(r_from))
            if r_to:   rqs = rqs.filter(received_at__lte=datetime.date.fromisoformat(r_to))
        except ValueError:
            pass
        if r_code:
            rqs = rqs.filter(product__product_code=r_code)
        receive_records = [{
            "received_at":  r.received_at,
            "product_code": r.product.product_code,
            "jan_code":     r.product.jan_code,
            "name":         r.product.name,
            "category":     r.product.category.name,
            "expiry_date":  r.expiry_date,
            "location":     r.location,
            "quantity":     r.quantity,
            "remarks":      r.remarks,
            "is_confirmed": r.is_confirmed,
        } for r in rqs]
        r_total_qty         = sum(r["quantity"] for r in receive_records)
        r_unconfirmed_count = sum(1 for r in receive_records if not r["is_confirmed"])
        r_confirmed_count   = len(receive_records) - r_unconfirmed_count

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
        "r_total_qty": r_total_qty,
        "r_unconfirmed_count": r_unconfirmed_count,
        "r_confirmed_count": r_confirmed_count,
        "r_reset": r_reset,
        # 出庫
        "s_from": s_from, "s_to": s_to, "s_code": s_code,
        "s_searched": s_searched, "ship_records": ship_records,
        "ship_total": ship_total,
        "s_reset": s_reset,
        "unconfirmed_count": unconfirmed_count,
        "confirmed_count":   confirmed_count,
        "query_string": request.GET.urlencode(),
        "user_role": _get_user_role(request.user),
    })


@login_required
def history_csv_view(request):
    tab = request.GET.get("tab", "receive")

    if tab == "receive":
        r_from = request.GET.get("r_from", "")
        r_to   = request.GET.get("r_to",   "")
        r_code = request.GET.get("r_code", "").strip()
        rqs = ReceiveHistory.objects.select_related("product__category").order_by("received_at", "id")
        try:
            if r_from: rqs = rqs.filter(received_at__gte=datetime.date.fromisoformat(r_from))
            if r_to:   rqs = rqs.filter(received_at__lte=datetime.date.fromisoformat(r_to))
        except ValueError:
            pass
        if r_code:
            rqs = rqs.filter(product__product_code=r_code)
        filename = "入庫履歴.csv"
        headers  = ["入荷日", "商品コード", "JANコード", "商品名", "カテゴリ", "賞味期限", "入庫先", "入庫数", "備考", "確定状態"]
        rows = [[
            r.received_at.strftime("%Y/%m/%d"),
            r.product.product_code, r.product.jan_code, r.product.name, r.product.category.name,
            r.expiry_date.strftime("%Y/%m/%d"),
            "店頭" if r.location == "store" else "倉庫",
            r.quantity, r.remarks,
            "確定" if r.is_confirmed else "仮",
        ] for r in rqs]
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
