from decimal import Decimal
from sqlalchemy import func, select
from app.database import SessionLocal
from app.models import Customer, Product, Order, OrderItem


# ---------------------------------------------------------------
# Сценарий 1: Оформление заказа
# items — список кортежей (product_id, quantity)
# ---------------------------------------------------------------
def place_order(customer_id: int, items: list[tuple[int, int]]):
    session = SessionLocal()
    try:
        # Создаём заказ с нулевой суммой
        order = Order(customerid=customer_id, totalamount=0)
        session.add(order)
        session.flush()  # нужен flush, чтобы получить order.orderid до commit
        print(f"Создан заказ #{order.orderid}")

        # Добавляем каждую позицию заказа
        for product_id, quantity in items:
            product = session.get(Product, product_id)
            if product is None:
                raise ValueError(f"Продукт #{product_id} не найден")
            subtotal = product.price * quantity

            item = OrderItem(
                orderid=order.orderid,
                productid=product_id,
                quantity=quantity,
                subtotal=subtotal,
            )
            session.add(item)
            print(f"  {product.productname} x{quantity} = {subtotal} руб.")

        # Считаем сумму всех Subtotal и обновляем TotalAmount
        session.flush()
        total = session.execute(
            select(func.sum(OrderItem.subtotal)).where(OrderItem.orderid == order.orderid)
        ).scalar() or Decimal(0)

        order.totalamount = total
        session.commit()
        print(f"Итого: {total} руб.")

    except Exception as e:
        session.rollback()
        print(f"Ошибка: {e}")
    finally:
        session.close()


# ---------------------------------------------------------------
# Сценарий 2: Обновление email клиента
# ---------------------------------------------------------------
def update_customer_email(customer_id: int, new_email: str):
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise ValueError(f"Клиент #{customer_id} не найден")

        customer.email = new_email
        session.commit()
        print(f"Email клиента #{customer_id} → {new_email}")

    except Exception as e:
        session.rollback()
        print(f"Ошибка: {e}")
    finally:
        session.close()


# ---------------------------------------------------------------
# Сценарий 3: Добавление нового продукта
# ---------------------------------------------------------------
def add_product(name: str, price: float):
    session = SessionLocal()
    try:
        product = Product(productname=name, price=price)
        session.add(product)
        session.commit()
        print(f"Добавлен продукт '{name}', цена {price} руб. (ID={product.productid})")

    except Exception as e:
        session.rollback()
        print(f"Ошибка: {e}")
    finally:
        session.close()
