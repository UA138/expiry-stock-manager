"""
賞味期限が近い在庫ロットをSlackに通知するコマンド。
Usage: python manage.py notify_expiry
"""
import datetime

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from stock.models import StockLot

WARNING_DAYS = 3


class Command(BaseCommand):
    help = "期限間近・期限切れの在庫ロットをSlackに通知します"

    def handle(self, *args, **options):
        webhook_url = settings.SLACK_WEBHOOK_URL
        if not webhook_url:
            self.stdout.write(self.style.ERROR("SLACK_WEBHOOK_URL が設定されていません。"))
            return

        today = datetime.date.today()
        threshold = today + datetime.timedelta(days=WARNING_DAYS)

        lots = (
            StockLot.objects.select_related("product")
            .filter(expiry_date__lte=threshold)
            .exclude(store_quantity=0, warehouse_quantity=0)
            .order_by("expiry_date")
        )

        if not lots:
            self.stdout.write("通知対象のロットはありません。")
            return

        lines = ["*【在庫アラート】期限間近・期限切れの商品*"]
        for lot in lots:
            days_left = (lot.expiry_date - today).days
            label = "期限切れ" if days_left < 0 else f"残り{days_left}日"
            total_qty = lot.store_quantity + lot.warehouse_quantity
            lines.append(
                f"・{lot.product.name}（{lot.product.product_code}） "
                f"期限:{lot.expiry_date}（{label}） 在庫:{total_qty}個"
            )

        message = "\n".join(lines)
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()
        self.stdout.write(self.style.SUCCESS(f"{lots.count()}件のロットを通知しました。"))