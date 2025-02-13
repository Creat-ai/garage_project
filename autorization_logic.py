import hashlib
import html
import logging
import re
from aiogram import types
import requests
import xml.etree.ElementTree as ET

from db import Database
from utils import parse_find_vehicle_by_plate_number

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
    # Validate VIN before request
    if not re.fullmatch(r"^[A-HJ-NPR-Z0-9]{17}$", user_vin):
        raise ValueError(f"Некорректный VIN: {user_vin}")
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
            logging.debug("SOAP failure-logging exception")
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
        if not selected_vehicle["vehicleid"] or selected_vehicle["vehicleid"] == "0":
            await message.reply("Ошибка: невозможность добавить автомобиль с некорректными данными.")
            return

        # Добавить в базу данных
        car_id = db.add_vehicle_to_database(
            vin=selected_vehicle["vin"],  # Используем VIN из ответа SOAP
            brand=selected_vehicle["brand"],
            model=selected_vehicle["name"],
            catalog=selected_vehicle["catalog"],
            ssd=selected_vehicle["ssd"],
            vehicleid=selected_vehicle["vehicleid"]  # Сохраняем VehicleId
        )
        if car_id:
            db.add_vehicle_to_garage(user_id, car_id)
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
    Парсит SOAP-ответ и возвращает список автомобилей.
    """
    try:
        # Парсим основной XML
        root = ET.fromstring(response_text)
        namespace = "{http://WebCatalog.Kito.ec}"

        # Ищем элемент <return>
        return_element = root.find(".//" + namespace + "return")

        if return_element is None or not return_element.text:
            logging.warning("Элемент <return> отсутствует или пуст в ответе. Автомобили не найдены.")
            return []

        # Декодируем экранированный XML в <return>
        raw_xml = return_element.text.strip()
        logging.debug(f"Сырой XML <return>: {raw_xml}")

        cleaned_xml = cleanup_invalid_xml(raw_xml)
        if not cleaned_xml:
            raise ValueError("Ошибка очистки XML из элемента <return>")

        # Парсим внутренний XML из <return>
        inner_root = ET.fromstring(cleaned_xml)

        # Ищем элемент FindVehicleByVIN
        vehicles_element = inner_root.find("FindVehicleByVIN")
        vehicles = []

        # Обработка автомобилей
        for row in vehicles_element.findall("row"):
            all_attribs = row.attrib
            logging.debug(f"Итерация строки данных: {all_attribs}")

            # Проверяем vehicleid: если оно "0", проверяем другие важные поля
            vehicleid = all_attribs.get("vehicleid")
            if vehicleid == "0" and not all_attribs.get("brand") and not all_attribs.get("catalog"):
                logging.warning(f"Пропуск строки с некорректным vehicleid: {all_attribs}")
                continue

            # Формируем объект автомобиля
            vehicle = {
                "brand": all_attribs.get("brand", "Неизвестно"),
                "catalog": all_attribs.get("catalog", "Неизвестно"),
                "name": all_attribs.get("name", "Неизвестно"),
                "ssd": all_attribs.get("ssd"),
                "vehicleid": vehicleid,
                "vin": user_vin,
            }
            vehicles.append(vehicle)
        return vehicles

    except Exception as e:
        logging.error(f"Ошибка обработки SOAP-ответа: {e}")
        return []

def cleanup_invalid_xml(xml_str: str) -> str:
    """
    Очищает строку XML от некорректных символов, включая пробелы,
    экранированные кавычки и неверные элементы.
    """
    logging.debug(f"Исходный XML для очистки: {xml_str}")
    try:
        # Удаляем недопустимые символы (невидимые и ошибки кодировки)
        xml_str = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', xml_str)

        # Исправляем двойное экранирование кавычек в value атрибутов: &quot;
        xml_str = re.sub(r'"&quot;([A-Za-z0-9\-]+?)&quot;"', r'"&quot;\1&quot;"', xml_str)

        # Исправляем прямые кавычки внутри атрибутов, преобразуя их в допустимый формат
        xml_str = xml_str.replace('"&quot;', '&quot;').replace('&quot;"', '&quot;')

        # Проверяем возможность парсинга
        ET.fromstring(xml_str)  # Если некорректен, выбросит ParseError
    except ET.ParseError as e:
        logging.error(f"Ошибка валидности XML: {e}")
        logging.debug(f"Некорректный XML после обработки: \n{xml_str}")
        raise ValueError("Некорректный XML получен после очистки.")

    return xml_str

def validate_and_fix_xml_attribute(attr_value: str) -> str:
    """
    Проверяет и фиксирует значение атрибута XML.
    """
    # Экранируем кавычки внутри значения
    fixed_value = attr_value.replace('"', '&quot;').replace("'", "&apos;")
    return fixed_value

def check_user_credentials(userlogin: str, password: str):
    """
    Проверка учетных данных пользователя через API ABCP.
    """
    try:
        logging.debug(f"Проверка учетных данных: логин={userlogin}, пароль=*****")
        logging.info("Начало проверки учетных данных пользователя.")
        logging.info("Отправка запроса для верификации учетных данных")

        password_hash = hashlib.md5(password.encode()).hexdigest()
        logging.debug(f"Хэш пароля: {password_hash}")

        api_url = f"https://abcp44086.public.api.abcp.ru/user/info?userlogin={userlogin}&userpsw={password_hash}"
        logging.debug(f"Сформирован URL: {api_url}")

        logging.debug(f"URL для проверки учетных данных: {api_url}")
        response = requests.get(api_url)
        logging.debug(f"Ответ от API: {response.text}")
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

def search_vehicle_details(catalog: str, vehicle_id: str, ssd: str, part_name: str):
    """
    Поиск запчастей по названию через Laximo API методом SearchVehicleDetails.
    """
    try:
        # Формируем команду для SOAP-запроса
        command = (
            f"SearchVehicleDetails:Query={part_name}"
            f"|Catalog={catalog}"
            f"|VehicleId={vehicle_id}"
            f"|ssd={ssd}"
            f"|Locale=ru_RU"
        )

        # Добавить логирование:
        logging.debug(f"Команда для поиска: {command}")

        # Генерируем HMAC
        hmac_signature = generate_hmac(command, LAXIMO_PASSWORD)

        # Формируем SOAP-запрос
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

        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "SOAPAction": "urn:QueryDataLogin",
        }

        # Выполняем запрос
        logging.debug(f"Отправка SOAP-запроса:\n{soap_body}")
        response = requests.post(SOAP_URL, data=soap_body.encode("utf-8"), headers=headers)

        # Проверка ответа
        if response.status_code == 200:
            logging.info("Поиск запчастей выполнен успешно.")
            return parse_search_vehicle_details_response(response.text)
        else:
            logging.error(f"Ошибка поиска запчастей (код {response.status_code}): {response.text}")
            return {"error": "Не удалось выполнить поиск запчастей"}
    except Exception as e:
        logging.error(f"Ошибка при поиске запчастей: {e}")
        return {"error": "Исключение при выполнении"}

def parse_search_vehicle_details_response(response_text: str) -> list:
    try:
        # Парсим основной XML
        root = ET.fromstring(response_text)
        namespace = "{http://WebCatalog.Kito.ec}"  # Пространство имен
        return_element = root.find(f".//{namespace}return")

        # Проверяем наличие <return>
        if return_element is None or not return_element.text:
            logging.error("Элемент <return> отсутствует в ответе.")
            return []  # Пустой результат в случае отсутствия данных

        # Обрабатываем вложенный XML
        raw_xml = return_element.text.strip()
        logging.debug(f"Вложенный XML: {raw_xml}")

        inner_root = ET.fromstring(raw_xml)
        search_results = []

        for row in inner_root.findall(".//row"):  # Ищем все элементы <row>
            oem = row.attrib.get("oem", "").strip()
            if not oem:
                logging.warning("Обнаружена строка без OEM, пропущена.")
                continue

            name = row.text.strip() if row.text else "Без имени"
            logging.debug(f"Найдена запчасть: {name} (OEM: {oem})")
            search_results.append({"oem": oem, "name": name})

        logging.info(f"Количество найденных запчастей: {len(search_results)}")
        return search_results

    except ET.ParseError as e:
        logging.error(f"Ошибка парсера XML: {e}")
        return []
    except Exception as e:
        logging.error(f"Произошла неизвестная ошибка: {e}")
        return []

def find_vehicle_by_plate_number(plate_number: str, locale="ru_RU", country_code="ru"):
    command = f"FindVehicleByPlateNumber:Locale={locale}|CountryCode={country_code}|PlateNumber={plate_number}"
    hmac_signature = generate_hmac(command, LAXIMO_PASSWORD)

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
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "SOAPAction": "urn:QueryDataLogin"
    }

    # Отправить запрос и обработать результат
    response = requests.post(SOAP_URL, data=soap_body.encode("utf-8"), headers=headers)

    if response.status_code == 200:
        logging.debug(f"Получен XML-ответ: {response.text}")  # Логируем ответ полностью
        if not isinstance(response.text, str):
            logging.error("Некорректный формат ответа от Laximo: ожидалась строка.")
            return ""
        return response.text
    else:
        logging.error(f"Ошибка запроса ({response.status_code}): {response.text}")
        return ""


def search_vehicle_combined(identifier: str, db: Database, locale="ru_RU"):
    """
    Комбинированный поиск по идентификатору (номер детали или VIN).
    """
    # Проверка номера детали
    try:
        db_result = db.get_vehicle_by_part_number(identifier)  # Используем part_number
        if db_result:
            return {"status": "found", "car": db_result}

        # Поиск через Laximo, если не найдено в БД
        command = f"FindVehicleByPlateNumber:Locale={locale}|CountryCode=ru|PlateNumber={identifier}"
        response = send_soap_request(command, user_vin=identifier)

        if response and response.get("status") == "success":
            vehicles = parse_find_vehicle_by_plate_number(response.get("data", ""))
            return {"status": "found", "car": vehicles}

        return {"status": "not_found"}
    except Exception as e:
        logging.error(f"Ошибка в поиске по номеру детали: {e}")
        return {"status": "error", "message": str(e)}



