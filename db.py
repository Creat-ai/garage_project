import logging
import sqlite3

DB_NAME = "bot_database.db"


class Database:
    def __init__(self):
        """Инициализация базы данных и подключение"""
        self.connection = sqlite3.connect(DB_NAME)
        self.cursor = self.connection.cursor()

    def add_user(self, telegram_id, abcp_user_id, userlogin, userpsw, code=None, email=None, name=None, mobile=None,
                 organization=None):
        """Добавление нового пользователя с Telegram ID и ABCP User ID"""
        self.cursor.execute("""
            INSERT INTO users (telegram_id, abcp_user_id, userlogin, userpsw, code, email, name, mobile, organization)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                abcp_user_id=excluded.abcp_user_id,
                userlogin=excluded.userlogin,
                userpsw=excluded.userpsw,
                code=excluded.code,
                email=excluded.email,
                name=excluded.name,
                mobile=excluded.mobile,
                organization=excluded.organization
        """, (telegram_id, abcp_user_id, userlogin, userpsw, code, email, name, mobile, organization))
        self.connection.commit()

    def add_car(self, vin, ssd, brand, catalog=None, name=None):
        """Добавление автомобиля"""
        self.cursor.execute("""
            INSERT INTO cars (vin, catalog, name, ssd, brand)
            VALUES (?, ?, ?, ?, ?)
        """, (vin, catalog, name, ssd, brand))
        self.connection.commit()

    def add_car_to_garage(self, user_id, car_id):
        """Связь автомобиля с пользователем (гараж)"""
        self.cursor.execute("""
            INSERT INTO user_garage (user_id, car_id)
            VALUES (?, ?)
        """, (user_id, car_id))
        self.connection.commit()

    def get_cars_by_user(self, user_id):
        """Получение всех автомобилей пользователя"""
        self.cursor.execute("""
            SELECT cars.car_id, cars.vin, cars.name, cars.brand
            FROM cars
            INNER JOIN user_garage ON cars.car_id = user_garage.car_id
            WHERE user_garage.user_id = ?
        """, (user_id,))
        return self.cursor.fetchall()

    def get_car_by_vin(self, vin, user_id):
        """Поиск автомобиля по VIN и пользователю"""
        self.cursor.execute("""
            SELECT cars.car_id, cars.vin, cars.name, cars.brand
            FROM cars
            INNER JOIN user_garage ON cars.car_id = user_garage.car_id
            WHERE cars.vin = ? AND user_garage.user_id = ?
        """, (vin, user_id))
        return self.cursor.fetchone()

    def prepare_add_car(self, user_id, vin, brand, model):
        """Сохранение автомобиля для последующего подтверждения"""
        self.cursor.execute("""
            INSERT INTO cars (vin, name, brand, catalog, ssd)
            VALUES (?, ?, ?, NULL, NULL)
            ON CONFLICT(vin) DO NOTHING
        """, (vin, f"{brand} {model}", brand))
        car_id = self.cursor.execute("SELECT car_id FROM cars WHERE vin = ?", (vin,)).fetchone()[0]
        self.cursor.execute("""
            INSERT INTO user_garage (user_id, car_id)
            VALUES (?, ?)
        """, (user_id, car_id))
        self.connection.commit()

    def get_pending_car(self, user_id):
        """Получение автомобиля для подтверждения (последнего добавленного)"""
        self.cursor.execute("""
            SELECT cars.vin, cars.name, cars.brand
            FROM cars
            INNER JOIN user_garage ON cars.car_id = user_garage.car_id
            WHERE user_garage.user_id = ?
            ORDER BY cars.car_id DESC LIMIT 1
        """, (user_id,))
        return self.cursor.fetchone()

    def get_user_by_id(self, telegram_id):
        """Получение данных пользователя по Telegram ID"""
        self.cursor.execute("""
            SELECT * FROM users WHERE telegram_id = ?
        """, (telegram_id,))
        result = self.cursor.fetchone()
        if result:
            return {
                "telegram_id": result[0],
                "userlogin": result[1],
                "userpsw": result[2],
                "abcp_user_id": result[3],
                "code": result[4],
                "email": result[5],
                "name": result[6],
                "mobile": result[7],
                "organization": result[8],
            }
        return None

    # === Новые методы ===

    def find_vehicle_in_garage(self, user_id, vin):
        """Поиск автомобиля по VIN в гараже пользователя"""
        self.cursor.execute("""
            SELECT cars.car_id, cars.vin, cars.name, cars.brand
            FROM cars
            INNER JOIN user_garage ON cars.car_id = user_garage.car_id
            WHERE cars.vin = ? AND user_garage.user_id = ?
        """, (vin, user_id))
        return self.cursor.fetchone()

    def find_vehicle_in_database(self, vin):
        """Поиск автомобиля по VIN в общей базе данных"""
        self.cursor.execute("""
            SELECT cars.car_id, cars.vin, cars.name, cars.brand
            FROM cars WHERE cars.vin = ?
        """, (vin,))
        return self.cursor.fetchone()

    def add_vehicle_to_garage(self, user_id, car_id):
        logging.debug(f"Добавляем в гараж: user_id={user_id}, car_id={car_id}")
        try:
            self.cursor.execute("""
                INSERT INTO user_garage (user_id, car_id)
                VALUES (?, ?)
                ON CONFLICT(user_id, car_id) DO NOTHING -- Предотвращение дублирования
            """, (user_id, car_id))
            self.connection.commit()
            logging.debug("Успешно добавлено в гараж")
        except sqlite3.Error as e:
            logging.error(f"Ошибка добавления автомобиля в гараж: {e}")

    def add_vehicle_to_database(self, vin, brand, model, catalog=None, ssd=None):
        """
        Добавление автомобиля в таблицу cars. Если автомобиль уже существует (по VIN), то не добавляется.
        """
        try:
            self.cursor.execute("""
                INSERT INTO cars (vin, name, brand, catalog, ssd)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(vin) DO NOTHING -- Предотвращение дублирования по VIN
            """, (vin, f"{brand} {model}", brand, catalog, ssd))
            self.connection.commit()

            # Получаем ID добавленного автомобиля (или уже существующего)
            car_id = self.cursor.execute("SELECT car_id FROM cars WHERE vin = ?", (vin,)).fetchone()
            if car_id:
                return car_id[0]
            return None
        except sqlite3.Error as e:
            logging.error(f"Ошибка при добавлении автомобиля в базу данных: {e}")
            return None

    def is_car_in_garage(self, user_id, car_id):
        """Проверка: есть ли автомобиль в гараже пользователя"""
        result = self.cursor.execute("""
            SELECT 1 FROM user_garage WHERE user_id = ? AND car_id = ?
        """, (user_id, car_id)).fetchone()
        return result is not None

