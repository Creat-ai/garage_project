import hashlib
import html
import logging
import re
from aiogram import types
import requests
import xml.etree.ElementTree as ET

# Конфигурация логина, пароля и URL сервиса
LAXIMO_LOGIN = "am409367"
LAXIMO_PASSWORD = "bDhNbbGh0Lf8zfW"
SOAP_URL = "https://ws.laximo.ru/ec.Kito.WebCatalog/services/Catalog.CatalogHttpSoap12Endpoint/"

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("auth.log"),
        logging.StreamHandler(),
    ],
)


def generate_hmac(command: str, password: str) -> str:
    """
    Генерация HMAC для подписи запросов.
    Склеивается команда + пароль пользователя, затем берется MD5.
    """
    hmac_data = command + password
    return hashlib.md5(hmac_data.encode("utf-8")).hexdigest()


def send_soap_request(command: str, user_vin: str) -> dict:
    try:
        # Генерация HMAC
        hmac_signature = generate_hmac(command, LAXIMO_PASSWORD)

        # SOAP-запрос
        soap_body = f"""
        <soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Body>
                <QueryDataLogin xmlns="http://WebCatalog.Kito.ec">
                    <request>{command}</request>
                    <login>{LAXIMO_LOGIN}</login>
                    <hmac>{hmac_signature}</hmac>
                </QueryDataLogin>
            </soap:Body>
        </soap:Envelope>
        """

        logging.debug(f"SOAP-запрос:\n{soap_body}")

        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "SOAPAction": "urn:QueryDataLogin",
        }
        response = requests.post(SOAP_URL, data=soap_body.encode("utf-8"), headers=headers)

        logging.debug(f"SOAP-ответ:\n{response.text}")

        if response.status_code == 200:
            logging.info("Запрос успешно выполнен.")
            # Передаем `user_vin` в `parse_soap_response`
            return parse_soap_response(response.text, user_vin)
        else:
            logging.error(f"Ошибка! Код ответа {response.status_code}. Ответ: {response.text}")
            return {"error": "Ошибка выполнения запроса"}
    except Exception as e:
        logging.error(f"Ошибка при отправке SOAP-запроса: {e}")
        return {"error": "Исключение при обработке"}

def format_vehicle_list(vehicles):
    """Форматирование списка автомобилей для текстового отправления"""
    lines = []
    for idx, vehicle in enumerate(vehicles, start=1):
        brand = vehicle["brand"]
        name = vehicle["name"]
        catalog = vehicle["catalog"]
        lines.append(f"{idx}. {brand} {name} ({catalog})")  # Пример строки вида: "1. MITSUBISHI GALANT (MMC202403)"
    lines.append("\nВведите номер автомобиля, чтобы выбрать его, или '0', чтобы отменить.")
    return "\n".join(lines)

async def process_vehicle_choice(message, vehicles, db):
    """
    Обработать выбор автомобиля пользователем
    """
    user_input = message.text

    try:
        choice = int(user_input)  # Преобразуем ввод в целое число
    except ValueError:
        # Если ввод не является числом, отправить уведомление
        await message.reply("Пожалуйста, введите номер автомобиля или '0' для отмены.")
        return

    if choice == 0:
        # Отменить выбор
        await message.reply("Выбор автомобиля отменен.")
        return

    if 1 <= choice <= len(vehicles):
        # Сохраняем выбранный автомобиль
        selected_vehicle = vehicles[choice - 1]
        user_id = message.from_user.id  # Telegram ID пользователя

        # Сохранить в базу данных
        car_id = db.add_vehicle_to_database(
            vin=selected_vehicle["vin"],  # Используем реальный VIN, который был добавлен из SOAP-ответа
            brand=selected_vehicle["brand"],
            model=selected_vehicle["name"],
            catalog=selected_vehicle["catalog"],
            ssd=selected_vehicle["ssd"]
        )
        if car_id:
            db.add_vehicle_to_garage(user_id, selected_vehicle["ssd"])
            await message.reply(
                f"✅ Автомобиль '{selected_vehicle['brand']} {selected_vehicle['name']}' добавлен в ваш гараж!"
            )
        else:
            await message.reply("Ошибка: невозможно добавить автомобиль в гараж.")
    else:
        await message.reply("Пожалуйста, выберите номер из списка или введите '0' для отмены.")


async def send_vehicle_options(chat_id, vehicles, bot):
    """Отправить список найденных автомобилей пользователю"""
    vehicle_list_text = format_vehicle_list(vehicles)  # Формируем текст списка
    await bot.send_message(chat_id, f"Найдены автомобили:\n\n{vehicle_list_text}")



def parse_soap_response(response_text: str, user_vin: str) -> list:
    """
    Парсинг SOAP-ответа, возвращающего список автомобилей.
    """
    try:
        root = ET.fromstring(response_text)
        namespace = "{http://WebCatalog.Kito.ec}"
        return_element = root.find(".//" + namespace + "return")

        if return_element is None or not return_element.text:
            logging.error("Вложенный элемент <return> отсутствует.")
            return []

        raw_xml = return_element.text.strip()
        logging.debug(f"Извлечённый вложенный XML: {raw_xml}")

        cleaned_xml = cleanup_invalid_xml(raw_xml)
        inner_root = ET.fromstring(cleaned_xml)

        vehicles_element = inner_root.find("FindVehicleByVIN")
        vehicles = []
        for row in vehicles_element.findall("row"):
            vehicle = {
                "brand": row.attrib.get("brand", "Неизвестно"),
                "catalog": row.attrib.get("catalog", "Неизвестно"),
                "name": row.attrib.get("name", "Неизвестно"),
                "ssd": row.attrib.get("ssd"),
                "vehicleid": row.attrib.get("vehicleid"),
                "vin": user_vin  # Добавляем VIN от пользователя
            }
            logging.debug(f"Парсинг автомобиля: {vehicle}")
            vehicles.append(vehicle)

        return vehicles
    except Exception as e:
        logging.error(f"Ошибка во время парсинга SOAP-ответа: {e}")
        return []


def cleanup_invalid_xml(xml_str: str) -> str:
    """
    Очищает строку XML от некорректных символов, экранирует вложенные кавычки.
    """
    try:
        # Удаляем запрещённые символы XML
        xml_str = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', xml_str)

        # Исправляем некорректные кавычки (вложенные) на "&quot;"
        def fix_attribute_value(match):
            attr_value = match.group(1)
            # Экранируем внутренние двойные кавычки
            fixed_value = attr_value.replace('"', '&quot;')
            return f'value="{fixed_value}"'

        # Регулярка на значение атрибута XML
        xml_str = re.sub(r'value="(.*?)"', fix_attribute_value, xml_str)

        # Проверяем верность итогового XML
        ET.fromstring(xml_str)

    except ET.ParseError as e:
        logging.error(f"Ошибка валидности XML: {e}")
        logging.debug(f"Некорректный XML после обработки: \n{xml_str}")
        return None

    return xml_str


def check_user_credentials(userlogin: str, password: str):
    """
    Проверка учетных данных пользователя через API ABCP.
    """
    try:
        logging.info("Начало проверки учетных данных пользователя.")

        password_hash = hashlib.md5(password.encode()).hexdigest()
        logging.debug(f"Хэш пароля: {password_hash}")

        api_url = f"https://abcp44086.public.api.abcp.ru/user/info?userlogin={userlogin}&userpsw={password_hash}"

        response = requests.get(api_url)
        logging.info(f"Код статуса ответа: {response.status_code}")

        if response.status_code == 200:
            user_data = response.json()
            logging.info("Авторизация успешна. Данные пользователя получены.")
            return user_data
        else:
            logging.warning(f"Ошибка авторизации. Код статуса: {response.status_code}")
            return None

    except requests.RequestException as e:
        logging.error(f"Ошибка во время запроса к API: {e}")
        return None

    except ValueError:
        logging.error("Не удалось обработать JSON-ответ от сервера.")
        return None


