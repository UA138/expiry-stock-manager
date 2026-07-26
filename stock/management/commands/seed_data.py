"""
初期ダミーデータをDBに投入するコマンド。
各データ種別ごとに存在チェックし、なければ追加する。
Usage: python manage.py seed_data
"""
import datetime

from django.core.management.base import BaseCommand

from stock.models import Category, Product, ReceiveHistory, ShipmentPlan, StockLot


class Command(BaseCommand):
    help = "初期データをDBに投入します（種別ごとに存在チェックしてスキップ）"

    def handle(self, *args, **options):
        # ── カテゴリ・商品・在庫ロット・出庫予定 ──────────────────────────────
        if Category.objects.exists():
            self.stdout.write(self.style.WARNING("基本データは既に存在するためスキップしました。"))
        else:
            cats = {
                "C001": Category.objects.create(code="C001", name="乳製品"),
                "C002": Category.objects.create(code="C002", name="インスタント食品"),
                "C003": Category.objects.create(code="C003", name="缶詰"),
                "C004": Category.objects.create(code="C004", name="ベーカリー"),
                "C005": Category.objects.create(code="C005", name="飲料"),
            }

            products = {
                "P0001": Product.objects.create(
                    product_code="P0001", jan_code="4901234567890",
                    name="牛乳 1L", category=cats["C001"],
                    shelf_life_days=14, mall_limit_days=5,
                ),
                "P0002": Product.objects.create(
                    product_code="P0002", jan_code="4901234567891",
                    name="ヨーグルト 4個パック", category=cats["C001"],
                    shelf_life_days=21, mall_limit_days=7,
                ),
                "P0003": Product.objects.create(
                    product_code="P0003", jan_code="4901234567892",
                    name="カップ麺", category=cats["C002"],
                    shelf_life_days=365, mall_limit_days=60,
                ),
                "P0004": Product.objects.create(
                    product_code="P0004", jan_code="4901234567893",
                    name="缶詰（さば）", category=cats["C003"],
                    shelf_life_days=1095, mall_limit_days=90,
                ),
                "P0005": Product.objects.create(
                    product_code="P0005", jan_code="4901234567894",
                    name="パン", category=cats["C004"],
                    shelf_life_days=7, mall_limit_days=3,
                ),
            }

            StockLot.objects.create(
                product=products["P0001"], expiry_date=datetime.date(2026, 7, 20),
                store_quantity=8, warehouse_quantity=4,
            )
            StockLot.objects.create(
                product=products["P0001"], expiry_date=datetime.date(2026, 7, 15),
                store_quantity=5, warehouse_quantity=5,
            )
            StockLot.objects.create(
                product=products["P0002"], expiry_date=datetime.date(2026, 7, 12),
                store_quantity=20, warehouse_quantity=10,
            )
            StockLot.objects.create(
                product=products["P0003"], expiry_date=datetime.date(2026, 12, 1),
                store_quantity=30, warehouse_quantity=20,
            )
            StockLot.objects.create(
                product=products["P0004"], expiry_date=datetime.date(2027, 6, 25),
                store_quantity=5, warehouse_quantity=3,
            )
            StockLot.objects.create(
                product=products["P0005"], expiry_date=datetime.date(2026, 7, 9),
                store_quantity=12, warehouse_quantity=3,
            )

            ShipmentPlan.objects.create(
                product=products["P0001"], ship_date=datetime.date(2026, 7, 1),
                location="store", quantity=6, remarks="楽天",
            )
            ShipmentPlan.objects.create(
                product=products["P0001"], ship_date=datetime.date(2026, 7, 5),
                location="warehouse", quantity=3, remarks="Yahoo!",
            )
            ShipmentPlan.objects.create(
                product=products["P0003"], ship_date=datetime.date(2026, 7, 15),
                location="store", quantity=10, remarks="",
            )

            self.stdout.write(self.style.SUCCESS("基本データを投入しました。"))

        # ── 入庫履歴（ReceiveHistory） ─────────────────────────────────────────
        if ReceiveHistory.objects.exists():
            self.stdout.write(self.style.WARNING("入庫履歴データは既に存在するためスキップしました。"))
        else:
            try:
                prods = {p.product_code: p for p in Product.objects.filter(
                    product_code__in=["P0001", "P0002", "P0003", "P0004", "P0005"]
                )}
                receive_seed = [
                    ("P0001", datetime.date(2026, 7, 1),  datetime.date(2026, 7, 20), "store",     12,  ""),
                    ("P0002", datetime.date(2026, 7, 1),  datetime.date(2026, 7, 12), "store",     24,  ""),
                    ("P0003", datetime.date(2026, 7, 2),  datetime.date(2026, 12, 1), "warehouse", 50,  ""),
                    ("P0001", datetime.date(2026, 7, 3),  datetime.date(2026, 7, 15), "warehouse", 10,  "ロットB"),
                    ("P0004", datetime.date(2026, 7, 5),  datetime.date(2027, 6, 25), "store",     24,  ""),
                    ("P0005", datetime.date(2026, 7, 5),  datetime.date(2026, 7, 9),  "store",     20,  ""),
                    ("P0003", datetime.date(2026, 7, 5),  datetime.date(2026, 12, 1), "store",     -3,  "不良品返品"),
                ]
                for code, received_at, expiry_date, location, qty, remarks in receive_seed:
                    if code in prods:
                        ReceiveHistory.objects.create(
                            product=prods[code],
                            received_at=received_at,
                            expiry_date=expiry_date,
                            location=location,
                            quantity=qty,
                            remarks=remarks,
                        )
                self.stdout.write(self.style.SUCCESS("入庫履歴データを投入しました。"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"入庫履歴データの投入に失敗しました: {e}"))
