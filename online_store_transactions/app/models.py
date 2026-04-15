from decimal import Decimal
from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    customerid: Mapped[int]   = mapped_column(primary_key=True)
    firstname:  Mapped[str]   = mapped_column(String(50))
    lastname:   Mapped[str]   = mapped_column(String(50))
    email:      Mapped[str]   = mapped_column(String(100), unique=True)


class Product(Base):
    __tablename__ = "products"

    productid:   Mapped[int]     = mapped_column(primary_key=True)
    productname: Mapped[str]     = mapped_column(String(100))
    price:       Mapped[Decimal] = mapped_column(Numeric(10, 2))


class Order(Base):
    __tablename__ = "orders"

    orderid:     Mapped[int]      = mapped_column(primary_key=True)
    customerid:  Mapped[int]      = mapped_column(ForeignKey("customers.customerid"))
    orderdate:   Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    totalamount: Mapped[Decimal]  = mapped_column(Numeric(10, 2), default=0)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "orderitems"

    orderitemid: Mapped[int]     = mapped_column(primary_key=True)
    orderid:     Mapped[int]     = mapped_column(ForeignKey("orders.orderid"))
    productid:   Mapped[int]     = mapped_column(ForeignKey("products.productid"))
    quantity:    Mapped[int]     = mapped_column()
    subtotal:    Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order:   Mapped["Order"]   = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()
