import datetime

from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField("カテゴリ名", max_length=50, unique=True)

    class Meta:
        verbose_name = "カテゴリ"
        verbose_name_plural = "カテゴリ"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField("商品名", max_length=100)
    category = models.ForeignKey(
        Category, verbose_name="カテゴリ", on_delete=models.PROTECT, related_name="products"
    )

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品"
        ordering = ["name"]

    def __str__(self):
        return self.name


class StockItem(models.Model):
    STATUS_OK = "ok"
    STATUS_WARNING = "warning"
    STATUS_EXPIRED = "expired"

    product = models.ForeignKey(
        Product, verbose_name="商品", on_delete=models.CASCADE, related_name="stock_items"
    )
    quantity = models.PositiveIntegerField("在庫数")
    expiry_date = models.DateField("賞味期限")
    created_at = models.DateTimeField("登録日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "在庫"
        verbose_name_plural = "在庫"
        ordering = ["expiry_date"]

    def __str__(self):
        return f"{self.product.name}（{self.expiry_date}）"

    @property
    def status(self):
        days_left = (self.expiry_date - datetime.date.today()).days
        if days_left < 0:
            return self.STATUS_EXPIRED
        if days_left <= 3:
            return self.STATUS_WARNING
        return self.STATUS_OK


class UserProfile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "管理者"),
        (ROLE_STAFF, "スタッフ"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="ユーザー", on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField("権限", max_length=10, choices=ROLE_CHOICES, default=ROLE_STAFF)

    class Meta:
        verbose_name = "ユーザープロフィール"
        verbose_name_plural = "ユーザープロフィール"

    def __str__(self):
        return f"{self.user.username}（{self.get_role_display()}）"
