from app.database import engine, Base
from app.models import Customer, Product  # noqa: F401 — нужен импорт для create_all
from app.crud import place_order, update_customer_email, add_product
from sqlalchemy.orm import Session


def seed(session: Session):
    """Добавляем тестовые данные, если таблицы пустые."""
    if session.query(Customer).count() == 0:
        session.add_all([
            Customer(firstname="Иван",  lastname="Иванов",  email="ivan@mail.ru"),
            Customer(firstname="Мария", lastname="Петрова", email="maria@mail.ru"),
        ])

    if session.query(Product).count() == 0:
        session.add_all([
            Product(productname="Ноутбук",    price=45000.00),
            Product(productname="Мышь",       price=900.00),
            Product(productname="Клавиатура", price=1500.00),
        ])

    session.commit()


if __name__ == "__main__":
    # Создаём таблицы (если их нет)
    Base.metadata.create_all(engine)

    # Заполняем тестовыми данными
    with Session(engine) as s:
        seed(s)

    print("=== Сценарий 1: Оформление заказа ===")
    place_order(customer_id=1, items=[(1, 1), (2, 2)])  # 1 ноутбук + 2 мыши

    print("\n=== Сценарий 2: Обновление email ===")
    update_customer_email(customer_id=1, new_email="ivan_new@mail.ru")

    print("\n=== Сценарий 3: Добавление продукта ===")
    add_product(name="Монитор", price=18000.00)
