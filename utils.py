
import logging
import xml.etree.ElementTree as ET
from html import unescape


def parse_find_vehicle_by_plate_number(xml_response: str):
    """Парсит XML-ответ для поиска автомобиля по гос. номеру."""
    if not isinstance(xml_response, str):
        raise TypeError(f"Ожидалась строка XML, но получен объект типа {type(xml_response)}")

    try:
        # Парсим основной XML для получения <return>
        root = ET.fromstring(xml_response)
        logging.debug(f"Корневой XML: {ET.tostring(root, encoding='utf-8').decode('utf-8')}")  # Логирование XML

        # Находим нужный блок <return>
        namespace = "{http://WebCatalog.Kito.ec}"  # Пространство имён из XML-ответа
        return_element = root.find(f".//{namespace}return")

        if return_element is None or not return_element.text:
            logging.warning("Элемент <return> отсутствует или пуст в ответе.")
            return []

        # Декодируем содержимое <return> (убираем &lt; и &gt;)
        raw_xml = unescape(return_element.text.strip())
        logging.debug(f"Декодированный XML из <return>: {raw_xml}")

        # Парсим внутренний XML
        inner_root = ET.fromstring(raw_xml)
        vehicles_element = inner_root.find("FindVehicleByPlateNumber")
        if not vehicles_element:
            logging.warning("Тег <FindVehicleByPlateNumber> отсутствует в ответе.")
            return []

        vehicles = []

        # Извлекаем данные из <row>
        for row in vehicles_element.findall("row"):
            vehicle = {
                "brand": row.attrib.get("brand", "Неизвестно"),
                "catalog": row.attrib.get("catalog", "Неизвестно"),
                "name": row.attrib.get("name", "Неизвестно"),
                "ssd": row.attrib.get("ssd", ""),
                "vehicleid": row.attrib.get("vehicleid", ""),
                "vin": row.attrib.get("vin", None),
                "attributes": {}  # Атрибуты автомобиля
            }

            for attribute in row.findall("attribute"):
                key = attribute.attrib.get("key")
                value = attribute.attrib.get("value", "Не указано")
                if key:
                    vehicle["attributes"][key] = value

            vehicles.append(vehicle)
            logging.debug(f"Обработан автомобиль: {vehicle}")

        logging.info(f"Найдено автомобилей: {len(vehicles)}")
        return vehicles

    except ET.ParseError as e:
        logging.error(f"Ошибка при разборе XML: {e}")
        raise ValueError(f"Ошибка при разборе XML: {e}")

def format_vehicle_response(vehicles: list) -> str:
    """
    Форматирует список автомобилей для отображения пользователю.

    :param vehicles: Список автомобилей, возвращаемый после парсинга XML.
    :return: Строка с отформатированным списком автомобилей.
    """
    if not vehicles:
        return "К сожалению, не удалось найти автомобили."

    response = "🚗 Найденные автомобили:\n"
    for idx, vehicle in enumerate(vehicles, start=1):
        # Основные параметры автомобиля
        brand = vehicle.get("brand", "Неизвестно")
        name = vehicle.get("name", "Неизвестно")
        manufactured = vehicle["attributes"].get("date", "Дата выпуска неизвестна")
        body_style = vehicle["attributes"].get("bodyStyle", "Тип кузова неизвестен")
        engine = vehicle["attributes"].get("engine", "Двигатель не указан")
        transmission = vehicle["attributes"].get("transmission", "КПП не указана")
        vin = vehicle.get("vin", "Не указан")

        # Форматируем данные для вывода
        response += (
            f"{idx}. {brand} {name}\n"
            f"   📅 Выпущен: {manufactured}\n"
            f"   🏎️ Кузов: {body_style}\n"
            f"   ⚙️ Двигатель: {engine}\n"
            f"   🔧 Трансмиссия: {transmission}\n"
            f"   🔑 VIN: {vin}\n\n"
        )

    response += "Введите номер автомобиля, чтобы продолжить, или '0' для отмены."
    return response
