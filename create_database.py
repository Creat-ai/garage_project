import sqlite3

# Имя базы данных, которая будет создана
DB_NAME = "bot_database.db"


def create_database():
    """Функция для создания базы данных и необходимых таблиц"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Создание таблицы пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT, -- ID пользователя
                userlogin TEXT NOT NULL,                  -- Логин
                userpsw TEXT NOT NULL,                    -- md5-хэш пароля
                code TEXT,                                -- Код пользователя
                email TEXT,                               -- Почта
                name TEXT,                                -- ФИО/Организация
                mobile TEXT,                              -- Телефон
                organization TEXT                         -- Название компании
            )
        """)

        # Создание таблицы автомобилей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cars (
                car_id INTEGER PRIMARY KEY AUTOINCREMENT, -- ID автомобиля
                vin TEXT NOT NULL UNIQUE,                 -- VIN-код
                catalog TEXT,                             -- Код каталога
                name TEXT,                                -- Наименование
                ssd TEXT NOT NULL,                        -- Данные сервера
                brand TEXT NOT NULL                       -- Производитель
            )
        """)

        # Создание таблицы запчастей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS details (
                detail_id INTEGER PRIMARY KEY AUTOINCREMENT, -- ID запчасти
                car_id INTEGER,                              -- Связь с авто
                oem TEXT NOT NULL,                           -- Артикул
                name TEXT,                                   -- Наименование запчасти
                FOREIGN KEY (car_id) REFERENCES cars(car_id) -- Внешний ключ к авто
            )
        """)

        # Создание таблицы связей "гарант - пользователь"
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_garage (
                garage_id INTEGER PRIMARY KEY AUTOINCREMENT, -- ID записи
                user_id INTEGER,                             -- ID пользователя
                car_id INTEGER,                              -- ID автомобиля
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (car_id) REFERENCES cars(car_id)
            )
        """)

        print("База данных и таблицы успешно созданы!")


# Запуск функции
if __name__ == "__main__":
    create_database()
