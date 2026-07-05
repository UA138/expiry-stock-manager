import datetime

from django.db import models

LOCATION_CHOICES = [("store", "店頭"), ("warehouse", "倉庫")]


class Category(models.Model):
    code = models.CharField("カテゴリコード", max_length=20, unique=True)
    name = models.CharField("カテゴリ名", max_length=50, unique=True)

    class Meta:
        verbose_name = "カテゴリ"
        verbose_name_plural = "カテゴリ"
        ordering = ["code"]

    def __str__(self):
        return self.name


class Product(models.Model):
    product_code = models.CharField("商品コード", max_length=50, unique=True)
    jan_code = models.CharField("JANコード", max_length=20, blank=True)
    name = models.CharField("商品名", max_length=200)
    category = models.ForeignKey(
        Category, verbose_name="カテゴリ", on_delete=models.PROTECT, related_name="products"
    )
    shelf_life_days = models.PositiveIntegerField("賞味期限（製造より○日）", null=True, blank=True)
    mall_limit_days = models.PositiveIntegerField("モール期限（残○日まで）", null=True, blank=True)

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品"
        ordering = ["product_code"]

    def __str__(self):
        return f"{self.product_code} {self.name}"


class StockLot(models.Model):
    product = models.ForeignKey(
        Product, verbose_name="商品", on_delete=models.CASCADE, related_name="stock_lots"
    )
    expiry_date = models.DateField("賞味期限")
    store_quantity = models.IntegerField("店頭在庫数", default=0)
    warehouse_quantity = models.IntegerField("倉庫在庫数", default=0)
    created_at = models.DateTimeField("登録日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "在庫ロット"
        verbose_name_plural = "在庫ロット"
        ordering = ["expiry_date"]

    def __str__(self):
        return f"{self.product.name}（期限:{self.expiry_date}）"

    @property
    def status(self):
        days_left = (self.expiry_date - datetime.date.today()).days
        if days_left < 0:
            return "expired"
        if days_left <= 3:
            return "warning"
        return "ok"

    @property
    def mall_status(self):
        limit = self.product.mall_limit_days
        if limit is None:
            return "mall_ok"
        days_left = (self.expiry_date - datetime.date.today()).days
        if days_left <= limit:
            return "mall_ng"
        if days_left <= limit + 5:
            return "mall_warning"
        return "mall_ok"


class ShipmentPlan(models.Model):
    product = models.ForeignKey(
        Product, verbose_name="商品", on_delete=models.PROTECT, related_name="shipment_plans"
    )
    ship_date = models.DateField("出荷日")
    location = models.CharField("出荷元", max_length=20, choices=LOCATION_CHOICES)
    quantity = models.PositiveIntegerField("出荷数")
    remarks = models.CharField("備考", max_length=30, blank=True)
    is_confirmed = models.BooleanField("確定済み", default=False)
    confirmed_at = models.DateTimeField("確定日時", null=True, blank=True)
    created_at = models.DateTimeField("登録日時", auto_now_add=True)

    class Meta:
        verbose_name = "出庫予定"
        verbose_name_plural = "出庫予定"
        ordering = ["ship_date", "product__product_code"]

    def __str__(self):
        status = "確定" if self.is_confirmed else "仮"
        return f"[{status}] {self.ship_date} {self.product.name} {self.quantity}個"


class ReceiveHistory(models.Model):
    product = models.ForeignKey(
        Product, verbose_name="商品", on_delete=models.PROTECT, related_name="receive_histories"
    )
    received_at = models.DateField("入荷日")
    expiry_date = models.DateField("賞味期限")
    location = models.CharField("入庫先", max_length=20, choices=LOCATION_CHOICES)
    quantity = models.IntegerField("入庫数")
    remarks = models.CharField("備考", max_length=30, blank=True)
    created_at = models.DateTimeField("登録日時", auto_now_add=True)

    class Meta:
        verbose_name = "入庫履歴"
        verbose_name_plural = "入庫履歴"
        ordering = ["-received_at", "-created_at"]

    def __str__(self):
        return f"{self.received_at} {self.product.name} {self.quantity}個"
