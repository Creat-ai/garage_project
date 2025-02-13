import hashlib
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from autorization_logic import check_user_credentials, search_vehicle_combined, find_vehicle_by_plate_number, \
    search_vehicle_details
from utils import parse_find_vehicle_by_plate_number, format_vehicle_response

from db import Database

# Токен бота
BOT_TOKEN = "7048753227:AAE0NF-erxLib9knlFGCjbZ3LQD5_zEj2tM"  # Замените на ваш токен
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключение к базе данных
db = Database()


# Главное меню
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поиск")],
            [KeyboardButton(text="Поиск запчастей")],
        ],
        resize_keyboard=True
    )


# Меню для неавторизованных пользователей
def unauthorized_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Авторизоваться")],
        ],
        resize_keyboard=True
    )


# Состояния FSM
class AuthStates(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()


class VinStates(StatesGroup):
    waiting_for_vin = State()  # Работа с гос. номером
    waiting_for_vin_by_vin = State()  # Работа с VIN-кодом
    waiting_for_selection = State()  # Выбор автомобиля
    waiting_for_part_name = State()

class PartStates(StatesGroup):
    waiting_for_part_name = State() # Ожидание ввода запчасти

async def is_user_authorized(user_id: int, message: types.Message) -> bool:
    """Проверка авторизации пользователя"""
    user = db.get_user_by_id(user_id)
    if not user:
        await message.answer(
            "Вы не авторизованы. Пожалуйста, нажмите 'Авторизоваться' в меню.",
            reply_markup=unauthorized_menu()
        )
        return False
    return True

@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    user = db.get_user_by_id(user_id)

    if user:
        await message.answer(
            f"Добро пожаловать, {user['name']}! Вы можете воспользоваться функциями бота.",
            reply_markup=main_menu()
        )
    else:
        await message.answer(
            "Добро пожаловать! Для работы с ботом необходимо авторизоваться.\n"
            "Нажмите на кнопку ниже.",
            reply_markup=unauthorized_menu()
        )


@dp.message(lambda message: message.text == "Авторизоваться")
async def authorize_user(message: types.Message, state: FSMContext):
    """Начало авторизации"""
    await state.set_state(AuthStates.waiting_for_login)
    await message.answer("Введите ваш логин:")


@dp.message(AuthStates.waiting_for_login)
async def get_login(message: types.Message, state: FSMContext):
    """Получение логина"""
    await state.update_data(userlogin=message.text)
    await state.set_state(AuthStates.waiting_for_password)
    await message.answer("Введите ваш пароль:")


@dp.message(AuthStates.waiting_for_password)
async def get_password(message: types.Message, state: FSMContext):
    """Авторизация пользователя"""
    user_data = await state.get_data()
    userlogin = user_data.get("userlogin")
    password = message.text
    telegram_id = message.from_user.id

    user_info = check_user_credentials(userlogin, password)
    if user_info:
        db.add_user(
            telegram_id=telegram_id,
            abcp_user_id=user_info.get("id"),
            userlogin=userlogin,
            userpsw=hashlib.md5(password.encode()).hexdigest(),
            code=user_info.get("code"),
            email=user_info.get("email"),
            name=user_info.get("name"),
            mobile=user_info.get("mobile"),
            organization=user_info.get("organization")
        )
        await message.answer(
            f"Авторизация прошла успешно! Добро пожаловать, {user_info['name']}!",
            reply_markup=main_menu()
        )
        await state.clear()
    else:
        await message.answer("Ошибка авторизации. Проверьте логин и пароль.")
        await state.clear()


@dp.message(lambda message: message.text == "Поиск")
async def handle_plate_or_vin_search(message: types.Message, state: FSMContext):
    """
    Начало сценария: сначала запрашивается гос. номер.
    Если ничего не найдено - предлагаем перейти к VIN.
    """
    user_id = message.from_user.id
    if not await is_user_authorized(user_id, message):
        return

    await message.answer("Введите гос. номер автомобиля для поиска.")
    await state.set_state(VinStates.waiting_for_vin)


@dp.message(VinStates.waiting_for_vin)
async def handle_plate_number_input(message: types.Message, state: FSMContext):
    """
    Обработка ввода гос. номера пользователя. Сначала ищем автомобиль в локальной базе,
    если не найден — переходим к запросу Laximo.
    """
    part_number = message.text.strip().upper()

    # Поиск в локальной базе данных через номер детали
    existing_vehicle = db.get_vehicle_by_part_number(part_number)

    if existing_vehicle:
        # Когда автомобиль найден в локальной базе
        response = (
            f"🚗 Найден автомобиль в локальной базе: {existing_vehicle['brand']} {existing_vehicle['name']}.\n"
            f"VIN: {existing_vehicle.get('vin', 'не указан')}.\n"
            f"Готовы искать запчасти по этому автомобилю. Укажите название детали."
        )
        await message.answer(response)

        # Передаем данные автомобиля в FSM (чтобы следующее состояние знало их)
        await state.update_data(
            car_id=existing_vehicle["car_id"],  # Используем car_id вместо id
            catalog=existing_vehicle.get("catalog"),  # Каталог Laximo
            vehicleid=existing_vehicle.get("vehicleid"),
            ssd=existing_vehicle.get("ssd")
        )
        await state.set_state(PartStates.waiting_for_part_name)  # Переход к поиску запчастей
        return

    # Если автомобиль не найден локально, ищем через Laximo
    try:
        await message.answer("🔄 Выполняется поиск автомобиля через Laximo...")
        xml_response = find_vehicle_by_plate_number(part_number)

        if not xml_response:
            await message.answer("⛔ Сервис Laximo не вернул данных. Попробуйте еще раз.")
            await state.clear()
            return

        vehicles = parse_find_vehicle_by_plate_number(xml_response)
        if vehicles:
            # Если автомобили найдены, предлагаем выбрать
            vehicle_list_text = format_vehicle_response(vehicles)
            await state.update_data(vehicles=vehicles, part_number=part_number)
            await message.answer(vehicle_list_text)
            await state.set_state(VinStates.waiting_for_selection)
        else:
            await message.answer(
                "🚫 Автомобиль не найден ни локально, ни через Laximo. Попробуйте поискать через VIN."
            )
            await state.set_state(VinStates.waiting_for_vin_by_vin)

    except Exception as e:
        logging.error(f"[handle_plate_number_input] Ошибка: {e}")
        await message.answer("⚠ Произошла ошибка. Пожалуйста, попробуйте позже.")
        await state.clear()






@dp.message(VinStates.waiting_for_selection)
async def handle_vehicle_selection(message: types.Message, state: FSMContext):
    """Обработка выбора автомобиля из списка, предложенного Laximo."""
    user_input = message.text.strip()

    if user_input == "0":
        await message.answer("Вы отменили процесс выбора автомобиля.", reply_markup=main_menu())
        await state.clear()
        return

    try:
        # Получаем список найденных автомобилей
        data = await state.get_data()
        vehicles = data.get("vehicles", [])

        selected_index = int(user_input) - 1  # Индекс выборки
        if 0 <= selected_index < len(vehicles):
            selected_vehicle = vehicles[selected_index]
            part_number = data.get("part_number")  # Введенный гос. номер

            # Сохраняем автомобиль в локальной базе
            car_id = db.add_vehicle_to_database(
                vehicleid=selected_vehicle["vehicleid"],
                vin=selected_vehicle["vin"],
                brand=selected_vehicle["brand"],
                name=selected_vehicle["name"],
                catalog=selected_vehicle["catalog"],
                ssd=selected_vehicle["ssd"],
                part_number=part_number  # Используем part_number как доп. идентификатор
            )
            if car_id:
                await state.update_data(car_id=car_id)  # Сохраняем car_id в FSM
                await message.answer("✅ Автомобиль добавлен. Введите название запчасти для поиска:")
                await state.set_state(PartStates.waiting_for_part_name)
            else:
                await message.answer("⚠ Не удалось сохранить автомобиль в базе данных.")
        else:
            await message.answer("Некорректный выбор. Попробуйте снова.")
    except ValueError:
        await message.answer("Введите корректный номер из списка.")



@dp.message(VinStates.waiting_for_vin_by_vin)
async def handle_vin_input(message: types.Message, state: FSMContext):
    """Обработка ввода VIN-кода"""
    vin = message.text.strip().upper()

    # Проверяем валидность VIN-кода
    if not re.fullmatch(r"^[A-HJ-NPR-Z0-9]{17}$", vin):
        await message.answer("Некорректный VIN-код. Проверьте его и попробуйте снова.")
        return

    # Поиск автомобиля по VIN
    result = search_vehicle_combined(vin, db)

    if result["status"] == "found":
        cars = result["car"]
        response = "🚗 Найдены автомобили по VIN-коду:\n"
        for idx, car in enumerate(cars if isinstance(cars, list) else [cars], start=1):
            response += f"{idx}. {car['brand']} {car['name']} (VIN: {car['vin']})\n"
        await message.answer(response)
    else:
        await message.answer("Автомобиль не найден. Попробуйте снова или свяжитесь с поддержкой.")
    await state.clear()



@dp.message(PartStates.waiting_for_part_name)
async def handle_part_name_input(message: types.Message, state: FSMContext):
    """
    Поиск запчастей: сначала локальный поиск в БД, затем запрос через Laximo при отсутствии совпадений.
    """
    part_name = message.text.strip().lower()  # Снижаем регистр ввода
    data = await state.get_data()  # Получаем данные автомобиля из состояния
    car_id = data.get("car_id")  # ID автомобиля

    if not car_id:
        await message.answer("Ошибка: автомобиль не найден. Начните с выбора автомобиля.")
        await state.clear()
        return

    # 1. Поиск запчастей в локальной базе
    filtered_parts = db.search_local_parts(car_id, part_name)
    if filtered_parts:
        # Если есть совпадения, формируем и отправляем ответ пользователю
        response = "📦 Найдены совпадающие запчасти в локальной базе:\n"
        for part in filtered_parts:
            response += f"🔧 {part[1]} (OEM: {part[2]})\n"
        await message.answer(response)
    else:
        # Если совпадений не найдено в БД, выполняем внешние запросы
        await message.answer("⛔ Запчасти не найдены локально. Выполняем поиск через Laximo. Подождите...")
        try:
            # Выполняем запрос через Laximo
            laximo_response = search_vehicle_details(
                catalog=data.get("catalog"),
                vehicle_id=data.get("vehicleid"),
                ssd=data.get("ssd"),
                part_name=part_name,
            )

            # Проверяем результат
            if isinstance(laximo_response, dict) and "error" in laximo_response:
                await message.answer(f"⚠ Ошибка при запросе в Laximo: {laximo_response['error']}")
            elif laximo_response:
                # Сохраняем в локальную базу все найденные запчасти
                db.save_parts_to_db(car_id, laximo_response)

                # Формируем и отправляем сообщение пользователю
                response = "📦 Найдены запчасти через Laximo:\n"
                for part in laximo_response:
                    response += f"🔧 {part['name']} (OEM: {part['oem']})\n"
                await message.answer(response)
            else:
                await message.answer("⛔ Запчасти не найдены даже через Laximo.")
        except Exception as e:
            logging.error(f"Ошибка при поиске в Laximo: {e}")
            await message.answer("⚠ Произошла ошибка при запросе в Laximo. Попробуйте позже.")

    # Завершаем сценарий
    await state.clear()







@dp.message(lambda message: True)
async def unknown_message(message: types.Message, state: FSMContext):
    """Обработка неизвестных сообщений"""
    current_state = await state.get_state()
    if current_state:
        await message.answer("Сообщение не распознано. Следуйте текущему сценарию.")
    else:
        await message.answer("Неизвестная команда. Воспользуйтесь меню.")


if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
