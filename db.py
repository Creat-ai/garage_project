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

    def get_cars_by_user(self, user_id):
        """Получение всех автомобилей пользователя."""
        try:
            self.cursor.execute("""
                SELECT cars.car_id, cars.vin, cars.name, cars.brand, cars.catalog, cars.ssd
                FROM cars
                INNER JOIN user_garage ON cars.car_id = user_garage.car_id
                WHERE user_garage.user_id = ?
            """, (user_id,))
            return self.cursor.fetchall()
        except Exception as e:
            logging.error(f"[get_cars_by_user] Ошибка в запросе: {e}")
            return []

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

    def get_vehicle_by_part_number(self, part_number: str):
        """
        Поиск автомобиля в базе данных по гос. номеру (part_number).
        """
        try:
            query = "SELECT * FROM cars WHERE part_number = ?"
            self.cursor.execute(query, (part_number,))
            row = self.cursor.fetchone()

            # Отладка результата
            if not row:
                logging.warning(f"Автомобиль с гос. номером {part_number} не найден в базе данных.")
                return None

            # Преобразование записи в словарь
            columns = [desc[0] for desc in self.cursor.description]
            result = dict(zip(columns, row))

            logging.debug(f"Найден автомобиль: {result}")
            return result
        except Exception as e:
            logging.error(f"[get_vehicle_by_part_number] Ошибка выполнения запроса: {e}")
            return None

    def find_vehicle_in_database(self, vin):
        """Поиск автомобиля по VIN в общей базе данных"""
        self.cursor.execute("""
            SELECT cars.car_id, cars.vin, cars.name, cars.brand
            FROM cars WHERE cars.vin = ?
        """, (vin,))
        return self.cursor.fetchone()

    def add_vehicle_to_database(self, vehicleid, vin, brand, name=None, catalog=None, ssd=None, part_number=None):
        """
        Добавляет автомобиль в таблицу cars.
        """
        query = """
            INSERT INTO cars (vehicleid, vin, brand, name, catalog, ssd, part_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.cursor.execute(query, (vehicleid, vin, brand, name, catalog, ssd, part_number))
            self.connection.commit()
            return self.cursor.lastrowid  # Возвращаем ID последней добавленной записи
        except sqlite3.IntegrityError:
            logging.error(f"Автомобиль с vehicleid={vehicleid} или VIN={vin} уже существует.")
            return None
        except Exception as e:
            logging.error(f"Ошибка при добавлении автомобиля: {e}")
            self.connection.rollback()
            return None


    def add_part_to_database(self, vin: str, oem: str, name: str):
        """
        Сохранение информации о запчастях в локальной базе данных.
        """
        try:
            query = """
            INSERT OR IGNORE INTO parts (vin, oem, name)
            VALUES (?, ?, ?)
            """
            self.cursor.execute(query, (vin, oem, name))
            self.connection.commit()
            logging.info(f"Запчасть {name} (OEM: {oem}) для VIN {vin} успешно добавлена в базу.")
        except Exception as e:
            logging.error(f"Ошибка при добавлении запчасти в базу данных: {e}")

    # Поиск запчастей по VIN и названию

    def search_local_parts(self, car_id: int, part_name: str) -> list:
        """
        Осуществляет поиск запчастей в локальной базе данных по ID автомобиля и названию/части названия детали.
        """
        try:
            # SQL-запрос с приведением регистра к нижнему
            query = """
                SELECT id, name, oem 
                FROM parts
                WHERE car_id = ? 
                AND (LOWER(name) LIKE LOWER(?) OR LOWER(oem) LIKE LOWER(?))
            """
            # Приводим часть названия к нижнему регистру
            search_query = f"%{part_name.strip().lower()}%"
            self.cursor.execute(query, (car_id, search_query, search_query))
            results = self.cursor.fetchall()
            if not results:
                logging.info(f"Нет совпадений для car_id={car_id} и part_name={part_name}.")
            return results
        except Exception as e:
            logging.error(f"Ошибка при поиске запчастей в базе: {e}")
            return []

    def save_parts_to_db(self, car_id: int, parts: list):
        """
        Сохраняет запчасти в базу данных с преобразованием регистра к нижнему.
        """
        try:
            for part in parts:
                oem = part.get("oem", "").strip().lower()  # Приводим к нижнему регистру
                name = part.get("name", "Неизвестно").strip().lower()  # Приводим к нижнему регистру

                # Пропуск, если данные уже существуют
                existing_query = """
                    SELECT 1 FROM parts WHERE car_id = ? AND LOWER(name) = LOWER(?) AND LOWER(oem) = LOWER(?)
                """
                self.cursor.execute(existing_query, (car_id, name, oem))
                if self.cursor.fetchone():
                    logging.info(f"Запчасть {name} (OEM: {oem}) уже существует в базе. Пропуск.")
                    continue

                # Вставка новой запчасти
                insert_query = """
                    INSERT INTO parts (car_id, name, oem) VALUES (?, ?, ?)
                """
                self.cursor.execute(insert_query, (car_id, name, oem))
                logging.info(f"Добавлена запчасть: {name} (OEM: {oem})")

            self.connection.commit()
        except Exception as e:
            logging.error(f"Ошибка при сохранении запчастей в базу данных: {e}")



