import hashlib
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram import F, types


from autorization import check_user_credentials, send_soap_request
from db import Database  # Импорт вашей базы данных

# Токен бота
BOT_TOKEN = "7048753227:AAE0NF-erxLib9knlFGCjbZ3LQD5_zEj2tM"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключение к базе данных
db = Database()


# Кнопка: Главное меню для авторизованных пользователей
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мой гараж")],
            [KeyboardButton(text="Поиск")],
        ],
        resize_keyboard=True
    )


# Кнопка: Меню для неавторизованных пользователей
def unauthorized_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Авторизоваться")],
        ],
        resize_keyboard=True
    )


# Состояния для выполнения команд
class AuthStates(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()


class VinStates(StatesGroup):
    waiting_for_vin = State()
    waiting_for_selection = State()


# Проверка авторизации пользователя
async def is_user_authorized(user_id: int, message: types.Message) -> bool:
    """
    Проверяет, авторизован ли пользователь.
    :param user_id: Telegram ID пользователя.
    :param message: Сообщение пользователя.
    :return: True, если авторизован; False, если нет.
    """
    user = db.get_user_by_id(user_id)
    if not user:
        await message.answer(
            "Вы не авторизованы. Пожалуйста, нажмите 'Авторизоваться' в меню.",
            reply_markup=unauthorized_menu()
        )
        return False
    return True


# Валидация VIN-кода
def validate_vin(vin: str) -> str:
    """
    Проверка валидности VIN-кода.
    """
    vin = vin.strip().upper()
    if len(vin) == 17 and vin.isalnum():
        return vin
    return None


# Обработчик команды /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
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


async def send_vehicle_options(chat_id, vehicles, bot):
    """ Отправка пользователю списка найденных автомобилей """
    buttons = []
    for idx, vehicle in enumerate(vehicles):
        brand = vehicle["brand"]
        name = vehicle["name"]
        catalog = vehicle["catalog"]
        text = f"{brand} {name} ({catalog})"

        # Кнопка на каждом автомобиле для подтверждения
        buttons.append(
            types.InlineKeyboardButton(text=text, callback_data=f"confirm_car_{idx}")
        )

    # Добавляем кнопку отмены
    buttons.append(
        types.InlineKeyboardButton(text="Отменить", callback_data="cancel_car")
    )

    # Создаем клавиатуру
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(*buttons)

    # Отправляем сообщение с клавиатурой
    await bot.send_message(
        chat_id, "Выберите ваш автомобиль:", reply_markup=keyboard
    )

# Обработчик кнопки "Авторизоваться"
@dp.message(lambda message: message.text == "Авторизоваться")
async def authorize_user(message: types.Message, state: FSMContext):
    await message.answer("Введите ваш логин:")
    await state.set_state(AuthStates.waiting_for_login)


# Шаг 1: Получение логина
@dp.message(AuthStates.waiting_for_login)
async def get_login(message: types.Message, state: FSMContext):
    await state.update_data(userlogin=message.text)
    await message.answer("Введите ваш пароль:")
    await state.set_state(AuthStates.waiting_for_password)


# Шаг 2: Получение пароля и проверка учетных данных
@dp.message(AuthStates.waiting_for_password)
async def get_password(message: types.Message, state: FSMContext):
    telegram_id = message.from_user.id

    # Получаем данные из состояния
    user_data = await state.get_data()
    userlogin = user_data.get("userlogin")
    password = message.text

    # Проверяем учетные данные пользователя через API
    user_info = check_user_credentials(userlogin, password)
    if user_info:
        # Сохраняем данные пользователя в базу
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
        await message.answer("Ошибка авторизации, проверьте логин и пароль.")
        await state.clear()


# Обработчик кнопки "Мой гараж"
@dp.message(lambda message: message.text == "Мой гараж")
async def my_garage(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_authorized(user_id, message):
        return

    cars = db.get_cars_by_user(user_id)
    if cars:
        response = "Ваш гараж:\n\n"
        response += "\n".join(
            [f"🚗 {car[2]} — {car[3]} (VIN: {car[1]})" for car in cars]
        )
        await message.answer(response)
    else:
        await message.answer("Ваш гараж пуст. Вы можете найти и добавить автомобиль через поиск.")


# Обработчик кнопки "Поиск"
@dp.message(lambda message: message.text == "Поиск")
async def vin_search_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await is_user_authorized(user_id, message):
        return

    await state.set_state(VinStates.waiting_for_vin)
    await message.answer("Введите VIN-код автомобиля для поиска. Проверьте, что он состоит из 17 символов.")


@dp.message(VinStates.waiting_for_vin)
async def handle_vin_input(message: types.Message, state: FSMContext):
    vin = validate_vin(message.text)
    if not vin:
        await message.answer("Некорректный VIN-код. Проверьте его и попробуйте снова.")
        return

    # Формируем команду
    command = f"FindVehicleByVIN:Locale=ru_RU|VIN={vin}|Localized=true"

    # Передаем и `command`, и `vin` в `send_soap_request`
    vehicle_data = send_soap_request(command, vin)

    if "error" in vehicle_data:
        await message.answer(f"Ошибка при поиске автомобиля: {vehicle_data['error']}")
        await state.clear()
        return

    # Проверяем, что `vehicle_data` является списком
    if isinstance(vehicle_data, list) and len(vehicle_data) > 0:
        # Если найдено несколько автомобилей, выводим их список
        vehicles = vehicle_data
        response = "🚗 Найдены автомобили:\n\n"
        for idx, vehicle in enumerate(vehicles, start=1):
            response += (
                f"{idx}. Марка: {vehicle.get('brand')}, "
                f"Модель: {vehicle.get('name')}, "
                f"Каталог: {vehicle.get('catalog')}\n"
            )
        response += "\nВведите номер автомобиля, чтобы добавить его в гараж, или '0', чтобы отменить."
        await message.answer(response)

        # Сохраняем авто в состояние и переводим на следующий шаг
        await state.update_data(vehicles=vehicles)
        await state.set_state(VinStates.waiting_for_selection)
    else:
        # Если не найдено ни одного автомобиля
        await message.answer("Автомобиль не найден. Проверьте VIN и попробуйте снова.")
        await state.clear()





@dp.message(VinStates.waiting_for_selection)
async def process_vehicle_selection(message: types.Message, state: FSMContext):
    data = await state.get_data()
    vehicles = data.get("vehicles")
    if not vehicles:
        await message.answer("Произошла ошибка. Попробуйте снова начать поиск VIN-кода.")
        await state.clear()
        return

    # Проверяем пользовательский ввод (номер автомобиля)
    try:
        user_input = int(message.text.strip())
    except ValueError:
        await message.answer("Введите корректный номер автомобиля или '0', чтобы отменить.")
        return

    if user_input == 0:
        await message.answer("Выбор автомобиля отменен.")
        await state.clear()
        return

    if 1 <= user_input <= len(vehicles):
        selected_vehicle = vehicles[user_input - 1]
        user_id = message.from_user.id

        # VIN должен быть всегда привязан по умолчанию (получен от пользователя)
        vin = selected_vehicle.get("vin")
        if not vin:
            await message.answer("Не удалось найти VIN для выбранного автомобиля.")
            await state.clear()
            return

        # Сохраняем автомобиль в базу данных
        car_id = db.add_vehicle_to_database(
            vin=vin,  # VIN предоставлен пользователем
            brand=selected_vehicle["brand"],
            model=selected_vehicle["name"],
            catalog=selected_vehicle["catalog"],
            ssd=selected_vehicle["ssd"]
        )

        if car_id:
            # Проверяем, есть ли автомобиль в гараже
            if not db.is_car_in_garage(user_id, car_id):
                db.add_vehicle_to_garage(user_id, car_id)
                await message.answer(
                    f"✅ Автомобиль '{selected_vehicle['brand']} {selected_vehicle['name']}' добавлен в ваш гараж!"
                )
            else:
                await message.answer("Этот автомобиль уже есть в вашем гараже!")
        else:
            await message.answer("Ошибка: невозможно добавить этот автомобиль в гараж.")
        await state.clear()
    else:
        await message.answer("Введите корректный номер автомобиля или '0', чтобы отменить.")








# Обработчик случайных сообщений
@dp.message()
async def unknown_message(message: types.Message):
    await message.answer("Я не понимаю это сообщение. Выберите команду из меню ниже или введите VIN-код.")


if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
