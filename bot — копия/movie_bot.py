import asyncio
import logging
import aiohttp
import random
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация API (замените на свои ключи)
API_CONFIG = {
    # TMDB API (альтернатива IMDb, бесплатный)
    "tmdb_api_key": "Токен_API",  # Получить на https://www.themoviedb.org/settings/api
    "tmdb_base_url": "https://api.themoviedb.org/3",
    
    # Кинопоиск (требуется ключ API)
    "kinopoisk_api_key": "JТокен_API",  # Получить на https://kinopoisk.dev/
    "kinopoisk_base_url": "https://api.kinopoisk.dev/v1.4",
    
    # Kadikama (парсинг сайта)
    "kadikama_base_url": "https://kadikama.info",
}

# Настройки бота
BOT_TOKEN = "Токен_bot"
CACHE_DURATION = 3600  # Кеширование на 1 час

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Класс для хранения данных
@dataclass
class MediaItem:
    id: int
    title: str
    original_title: Optional[str]
    type: str  # movie, tv, animation
    genres: List[str]
    mood: List[str]
    description: str
    year: int
    rating: float
    duration: str
    poster_url: Optional[str]
    source: str  # tmdb, kinopoisk, kadikama

# Кеш для хранения результатов
media_cache = {}
cache_timestamps = {}

# Клавиатуры
def get_genres_keyboard() -> ReplyKeyboardMarkup:
    genres = ["комедия", "драма", "фантастика", "боевик", "триллер", 
              "романтика", "ужасы", "детектив", "приключения", "аниме", 
              "семейный", "мультфильм", "история", "биография"]
    
    buttons = [KeyboardButton(text=genre) for genre in genres]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    rows.append([KeyboardButton(text="✅ Готово")])
    
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_mood_keyboard() -> ReplyKeyboardMarkup:
    moods = ["весёлое", "грустное", "романтичное", "страшное", "захватывающее",
             "расслабляющее", "вдохновляющее", "ностальгическое", "интеллектуальное"]
    
    buttons = [KeyboardButton(text=mood) for mood in moods]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    rows.append([KeyboardButton(text="✅ Готово")])
    
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_type_keyboard() -> ReplyKeyboardMarkup:
    types = ["фильм", "сериал", "мультфильм", "аниме", "любой"]
    
    buttons = [KeyboardButton(text=type_) for type_ in types]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_reaction_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Буду смотреть!")],
            [KeyboardButton(text="➡️ Следующий вариант")]
        ],
        resize_keyboard=True
    )

def get_confirm_restart_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да, ищу дальше!")],
            [KeyboardButton(text="Нет, не сегодня")]
        ],
        resize_keyboard=True
    )

# Состояния FSM
class UserState(StatesGroup):
    choosing_genres = State()
    choosing_mood = State()
    choosing_type = State()
    viewing_recommendations = State()
    confirming_restart = State()

# API интеграции
class MovieAPIClient:
    def __init__(self):
        self.session = None
        
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def search_tmdb(self, genre_ids: List[int], media_type: str = "movie", page: int = 1) -> List[MediaItem]:
        """Поиск фильмов/сериалов через TMDB API"""
        try:
            session = await self.get_session()
            base_url = API_CONFIG["tmdb_base_url"]
            api_key = API_CONFIG["tmdb_api_key"]
            
            if not api_key or api_key == "ВАШ_TMDB_API_KEY":
                return []
            
            # Преобразуем жанры в ID TMDB
            genre_map = {
                "комедия": 35, "драма": 18, "фантастика": 878, "боевик": 28,
                "триллер": 53, "романтика": 10749, "ужасы": 27, "детектив": 9648,
                "приключения": 12, "аниме": 16, "семейный": 10751, "мультфильм": 16,
                "история": 36, "биография": 99
            }
            
            tmdb_genre_ids = [genre_map.get(g) for g in genre_ids if g in genre_map]
            
            url = f"{base_url}/discover/{media_type}"
            params = {
                "api_key": api_key,
                "language": "ru-RU",
                "sort_by": "popularity.desc",
                "page": page,
                "with_genres": "|".join(map(str, tmdb_genre_ids[:3]))
            }
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results", [])[:5]  # Берем топ-5
                    
                    media_items = []
                    for item in results:
                        # Получаем детальную информацию
                        detail_url = f"{base_url}/{media_type}/{item['id']}"
                        detail_params = {"api_key": api_key, "language": "ru-RU"}
                        
                        async with session.get(detail_url, params=detail_params) as detail_resp:
                            if detail_resp.status == 200:
                                detail = await detail_resp.json()
                                
                                media_type_str = "фильм" if media_type == "movie" else "сериал"
                                if "animation" in detail.get("genres", []):
                                    media_type_str = "мультфильм"
                                
                                media_items.append(MediaItem(
                                    id=item["id"],
                                    title=detail.get("title") or detail.get("name", "Без названия"),
                                    original_title=detail.get("original_title") or detail.get("original_name"),
                                    type=media_type_str,
                                    genres=[g["name"] for g in detail.get("genres", [])[:3]],
                                    mood=[],  # TMDB не предоставляет информацию о настроении
                                    description=detail.get("overview", "Описание отсутствует"),
                                    year=int(detail.get("release_date", "2023")[:4]) if detail.get("release_date") else 2023,
                                    rating=detail.get("vote_average", 0),
                                    duration=f"{detail.get('runtime', 0)} мин" if detail.get('runtime') else "Не указано",
                                    poster_url=f"https://image.tmdb.org/t/p/w500{detail.get('poster_path', '')}" if detail.get('poster_path') else None,
                                    source="tmdb"
                                ))
                    
                    return media_items
                
        except Exception as e:
            logger.error(f"TMDB API error: {e}")
            return []
    
    async def search_kinopoisk(self, genres: List[str], media_type: str = "movie") -> List[MediaItem]:
        """Поиск через Кинопоиск API"""
        try:
            session = await self.get_session()
            base_url = API_CONFIG["kinopoisk_base_url"]
            api_key = API_CONFIG["kinopoisk_api_key"]
            
            if not api_key or api_key == "ВАШ_KINOPOISK_API_KEY":
                return []
            
            # Маппинг жанров Кинопоиска
            genre_map_kp = {
                "комедия": "комедия", "драма": "драма", "фантастика": "фантастика",
                "боевик": "боевик", "триллер": "триллер", "романтика": "мелодрама",
                "ужасы": "ужасы", "детектив": "детектив", "приключения": "приключения",
                "аниме": "аниме", "семейный": "семейный", "мультфильм": "мультфильм",
                "история": "история", "биография": "биография"
            }
            
            kp_genres = [genre_map_kp.get(g) for g in genres if g in genre_map_kp]
            
            url = f"{base_url}/movie"
            params = {
                "lists": "top250",
                "limit": 10,
                "selectFields": ["id", "name", "alternativeName", "year", "rating", 
                                "genres", "description", "movieLength", "poster", "type"],
                "type": "movie" if media_type == "фильм" else "tv-series" if media_type == "сериал" else "cartoon"
            }
            
            if kp_genres:
                params["genres.name"] = kp_genres[0]  # Берем первый жанр для фильтрации
            
            headers = {"X-API-KEY": api_key}
            
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    docs = data.get("docs", [])[:5]
                    
                    media_items = []
                    for doc in docs:
                        media_type_str = "фильм"
                        if doc.get("type") == "tv-series":
                            media_type_str = "сериал"
                        elif doc.get("type") == "cartoon":
                            media_type_str = "мультфильм"
                        
                        # Определяем настроение по жанрам
                        mood_map = {
                            "комедия": ["весёлое"],
                            "драма": ["грустное", "вдохновляющее"],
                            "фантастика": ["захватывающее"],
                            "боевик": ["захватывающее"],
                            "триллер": ["страшное", "захватывающее"],
                            "мелодрама": ["романтичное"],
                            "ужасы": ["страшное"],
                            "детектив": ["интеллектуальное"],
                            "приключения": ["захватывающее"],
                            "аниме": ["вдохновляющее"],
                            "семейный": ["расслабляющее"],
                            "мультфильм": ["весёлое"],
                            "биография": ["вдохновляющее"]
                        }
                        
                        moods = []
                        for genre in doc.get("genres", []):
                            if genre.get("name") in mood_map:
                                moods.extend(mood_map[genre["name"]])
                        
                        media_items.append(MediaItem(
                            id=doc["id"],
                            title=doc.get("name", "Без названия"),
                            original_title=doc.get("alternativeName"),
                            type=media_type_str,
                            genres=[g["name"] for g in doc.get("genres", [])[:3]],
                            mood=list(set(moods))[:3],
                            description=doc.get("description", "Описание отсутствует")[:300] + "...",
                            year=doc.get("year", 2023),
                            rating=doc.get("rating", {}).get("kp", 0),
                            duration=f"{doc.get('movieLength', 0)} мин",
                            poster_url=doc.get("poster", {}).get("url") if doc.get("poster") else None,
                            source="kinopoisk"
                        ))
                    
                    return media_items
                
        except Exception as e:
            logger.error(f"Kinopoisk API error: {e}")
            return []
    
    async def search_kadikama(self, mood: str = None) -> List[MediaItem]:
        """Получение случайных рекомендаций с Kadikama"""
        try:
            # Kadikama.info - парсинг сайта (упрощенная версия)
            # В реальном проекте нужен парсинг с BeautifulSoup
            
            # Заглушка с локальной базой на случай недоступности API
            fallback_items = [
                MediaItem(
                    id=1001,
                    title="Ведьмак",
                    original_title="The Witcher",
                    type="сериал",
                    genres=["фантастика", "приключения", "драма"],
                    mood=["захватывающее", "мрачное"],
                    description="Геральт из Ривии, мутировавший охотник на чудовищ, путешествует по Континенту.",
                    year=2019,
                    rating=8.2,
                    duration="1 сезон",
                    poster_url=None,
                    source="kadikama"
                ),
                MediaItem(
                    id=1002,
                    title="Игра в кальмара",
                    original_title="Squid Game",
                    type="сериал",
                    genres=["триллер", "драма", "выживание"],
                    mood=["страшное", "захватывающее"],
                    description="Участники играют в детские игры на выживание ради большого денежного приза.",
                    year=2021,
                    rating=8.0,
                    duration="1 сезон",
                    poster_url=None,
                    source="kadikama"
                ),
                MediaItem(
                    id=1003,
                    title="Энканто",
                    original_title="Encanto",
                    type="мультфильм",
                    genres=["мультфильм", "фэнтези", "мюзикл"],
                    mood=["весёлое", "вдохновляющее"],
                    description="Магическая история о семье Мадригаль, живущей в волшебном доме в Колумбии.",
                    year=2021,
                    rating=7.2,
                    duration="1ч 42м",
                    poster_url=None,
                    source="kadikama"
                ),
            ]
            
            # Фильтрация по настроению если указано
            if mood:
                filtered = [item for item in fallback_items if mood in item.mood]
                return filtered if filtered else fallback_items
            
            return fallback_items
            
        except Exception as e:
            logger.error(f"Kadikama error: {e}")
            return []

# Инициализация API клиента
api_client = MovieAPIClient()

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Запуск бота"""
    await state.clear()
    
    await message.answer(
        "🎬 <b>Кинобот</b> - ваш персональный киноконсультант!\n\n"
        "Я помогу подобрать идеальный фильм или сериал на вечер.\n"
        "Использую данные из <b>TMDB, Кинопоиска и Kadikama</b>.\n\n"
        "Давайте начнем! Выберите один или несколько жанров:",
        parse_mode="HTML",
        reply_markup=get_genres_keyboard()
    )
    await state.set_state(UserState.choosing_genres)
    await state.update_data(genres=[], mood=[], media_type=None)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Справка по боту"""
    await message.answer(
        "🎬 <b>Помощь по Киноботу</b>\n\n"
        "<b>Команды:</b>\n"
        "/start - начать подбор\n"
        "/help - эта справка\n"
        "/trending - популярное сейчас\n\n"
        "<b>Источники данных:</b>\n"
        "• The Movie Database (TMDB)\n"
        "• Кинопоиск\n"
        "• Kadikama.info\n\n"
        "<b>Как работает:</b>\n"
        "1. Выберите жанры\n"
        "2. Выберите настроение\n"
        "3. Выберите тип\n"
        "4. Получайте персонализированные рекомендации!",
        parse_mode="HTML"
    )

@dp.message(Command("trending"))
async def cmd_trending(message: types.Message):
    """Популярные фильмы прямо сейчас"""
    try:
        # Получаем тренды с TMDB
        session = await api_client.get_session()
        api_key = API_CONFIG["tmdb_api_key"]
        
        if api_key and api_key != "ВАШ_TMDB_API_KEY":
            url = f"{API_CONFIG['tmdb_base_url']}/trending/movie/week"
            params = {"api_key": api_key, "language": "ru-RU"}
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    trending = data.get("results", [])[:5]
                    
                    response_text = "📈 <b>Популярное на этой неделе:</b>\n\n"
                    
                    for i, movie in enumerate(trending, 1):
                        title = movie.get("title", "Без названия")
                        rating = movie.get("vote_average", 0)
                        year = movie.get("release_date", "2023")[:4] if movie.get("release_date") else "2023"
                        
                        response_text += f"{i}. <b>{title}</b> ({year}) ⭐ {rating}/10\n"
                    
                    await message.answer(response_text, parse_mode="HTML")
                    return
        
        # Если API недоступно, показываем локальные данные
        await message.answer(
            "📈 <b>Сейчас в тренде:</b>\n\n"
            "1. <b>Дюна: Часть вторая</b> (2024) ⭐ 8.5/10\n"
            "2. <b>Оппенгеймер</b> (2023) ⭐ 8.3/10\n"
            "3. <b>Барби</b> (2023) ⭐ 7.5/10\n"
            "4. <b>Миссия невыполнима 7</b> (2023) ⭐ 7.0/10\n"
            "5. <b>Человек-паук: Паутина вселенных</b> (2023) ⭐ 8.7/10",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Trending error: {e}")
        await message.answer("😕 Не могу получить популярные фильмы. Попробуйте позже.")

# Обработка выбора жанров
@dp.message(UserState.choosing_genres)
async def process_genres(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    selected_genres = user_data.get("genres", [])
    
    if message.text == "✅ Готово":
        if not selected_genres:
            await message.answer("Пожалуйста, выберите хотя бы один жанр!")
            return
        
        await message.answer(
            f"✅ Выбраны жанры: <b>{', '.join(selected_genres)}</b>\n\n"
            "Теперь выберите настроение для просмотра:",
            parse_mode="HTML",
            reply_markup=get_mood_keyboard()
        )
        await state.set_state(UserState.choosing_mood)
        return
    
    valid_genres = ["комедия", "драма", "фантастика", "боевик", "триллер", 
                    "романтика", "ужасы", "детектив", "приключения", "аниме", 
                    "семейный", "мультфильм", "история", "биография"]
    
    if message.text not in valid_genres:
        await message.answer("Пожалуйста, выберите жанр из предложенных!")
        return
    
    if message.text in selected_genres:
        selected_genres.remove(message.text)
        await message.answer(f"❌ Жанр <b>'{message.text}'</b> удалён", parse_mode="HTML")
    else:
        selected_genres.append(message.text)
        await message.answer(f"✅ Жанр <b>'{message.text}'</b> добавлен!", parse_mode="HTML")
    
    await state.update_data(genres=selected_genres)
    
    if selected_genres:
        await message.answer(f"📋 Выбрано: <b>{', '.join(selected_genres)}</b>\nНажмите '✅ Готово' когда закончите", 
                           parse_mode="HTML")

# Обработка выбора настроения
@dp.message(UserState.choosing_mood)
async def process_mood(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    selected_mood = user_data.get("mood", [])
    
    if message.text == "✅ Готово":
        if not selected_mood:
            await message.answer("Пожалуйста, выберите хотя бы одно настроение!")
            return
        
        await message.answer(
            f"✅ Настроение: <b>{', '.join(selected_mood)}</b>\n\n"
            "Теперь выберите тип:",
            parse_mode="HTML",
            reply_markup=get_type_keyboard()
        )
        await state.set_state(UserState.choosing_type)
        return
    
    valid_moods = ["весёлое", "грустное", "романтичное", "страшное", "захватывающее",
                   "расслабляющее", "вдохновляющее", "ностальгическое", "интеллектуальное"]
    
    if message.text not in valid_moods:
        await message.answer("Пожалуйста, выберите настроение из предложенных!")
        return
    
    if message.text in selected_mood:
        selected_mood.remove(message.text)
        await message.answer(f"❌ Настроение <b>'{message.text}'</b> удалено", parse_mode="HTML")
    else:
        selected_mood.append(message.text)
        await message.answer(f"✅ Настроение <b>'{message.text}'</b> добавлено!", parse_mode="HTML")
    
    await state.update_data(mood=selected_mood)
    
    if selected_mood:
        await message.answer(f"📋 Выбрано: <b>{', '.join(selected_mood)}</b>\nНажмите '✅ Готово' когда закончите",
                           parse_mode="HTML")

# Обработка выбора типа
@dp.message(UserState.choosing_type)
async def process_type(message: types.Message, state: FSMContext):
    valid_types = ["фильм", "сериал", "мультфильм", "аниме", "любой"]
    
    if message.text not in valid_types:
        await message.answer("Пожалуйста, выберите тип из предложенных!")
        return
    
    await state.update_data(media_type=message.text)
    user_data = await state.get_data()
    
    # Показываем итоги
    summary = (
        f"🎯 <b>Ваши предпочтения:</b>\n\n"
        f"<b>Жанры:</b> {', '.join(user_data['genres'])}\n"
        f"<b>Настроение:</b> {', '.join(user_data['mood'])}\n"
        f"<b>Тип:</b> {user_data['media_type']}\n\n"
        f"🔍 Ищу рекомендации по вашим критериям..."
    )
    
    await message.answer(summary, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    
    # Ищем рекомендации из всех источников
    await search_recommendations(message, state)

async def search_recommendations(message: types.Message, state: FSMContext):
    """Поиск рекомендаций из всех источников"""
    user_data = await state.get_data()
    
    all_recommendations = []
    
    # Поиск из TMDB
    if API_CONFIG["tmdb_api_key"] and API_CONFIG["tmdb_api_key"] != "ВАШ_TMDB_API_KEY":
        tmdb_type = "movie"
        if user_data["media_type"] == "сериал":
            tmdb_type = "tv"
        elif user_data["media_type"] == "мультфильм":
            tmdb_type = "movie"  # TMDB не отделяет мультфильмы
        
        tmdb_results = await api_client.search_tmdb(
            genre_ids=user_data["genres"],
            media_type=tmdb_type
        )
        all_recommendations.extend(tmdb_results)
    
    # Поиск из Кинопоиска
    if API_CONFIG["kinopoisk_api_key"] and API_CONFIG["kinopoisk_api_key"] != "ВАШ_KINOPOISK_API_KEY":
        kp_results = await api_client.search_kinopoisk(
            genres=user_data["genres"],
            media_type=user_data["media_type"]
        )
        all_recommendations.extend(kp_results)
    
    # Поиск из Kadikama (основываясь на настроении)
    if user_data["mood"]:
        kadikama_results = await api_client.search_kadikama(mood=user_data["mood"][0])
        all_recommendations.extend(kadikama_results)
    
    # Если нет результатов из API, используем локальные данные
    if not all_recommendations:
        # Локальная база на случай если API недоступны
        local_db = [
            MediaItem(1, "Начало", "Inception", "фильм", ["фантастика", "триллер"], 
                     ["интеллектуальное", "захватывающее"], "Сны внутри снов...", 2010, 8.8, "2ч 28м", None, "local"),
            MediaItem(2, "Побег из Шоушенка", "The Shawshank Redemption", "фильм", ["драма"], 
                     ["вдохновляющее", "грустное"], "История надежды в тюрьме...", 1994, 9.3, "2ч 22м", None, "local"),
            MediaItem(3, "Король Лев", "The Lion King", "мультфильм", ["мультфильм", "драма"], 
                     ["трогательное", "вдохновляющее"], "История львёнка Симбы...", 1994, 8.5, "1ч 28м", None, "local"),
            MediaItem(4, "Острые козырьки", "Peaky Blinders", "сериал", ["криминал", "драма"], 
                     ["стильное", "захватывающее"], "Британская криминальная сага...", 2013, 8.8, "6 сезонов", None, "local"),
            MediaItem(5, "Друзья", "Friends", "сериал", ["комедия"], 
                     ["весёлое", "расслабляющее"], "Жизнь шести друзей в Нью-Йорке...", 1994, 8.9, "10 сезонов", None, "local"),
        ]
        
        # Фильтрация локальных данных
        filtered_local = []
        for item in local_db:
            # Фильтр по типу
            if user_data["media_type"] != "любой" and item.type != user_data["media_type"]:
                continue
            
            # Фильтр по жанрам
            if user_data["genres"] and not any(genre in item.genres for genre in user_data["genres"]):
                continue
            
            # Фильтр по настроению
            if user_data["mood"] and not any(mood in item.mood for mood in user_data["mood"]):
                continue
            
            filtered_local.append(item)
        
        all_recommendations = filtered_local if filtered_local else local_db[:3]
    
    # Убираем дубликаты по названию
    unique_recommendations = []
    seen_titles = set()
    for item in all_recommendations:
        if item.title not in seen_titles:
            seen_titles.add(item.title)
            unique_recommendations.append(item)
    
    # Сортируем по рейтингу и берем первые 10
    unique_recommendations.sort(key=lambda x: x.rating, reverse=True)
    recommendations = unique_recommendations[:10]
    
    if not recommendations:
        await message.answer(
            "😕 К сожалению, по вашим критериям ничего не найдено.\n"
            "Попробуйте изменить параметры поиска с помощью /start"
        )
        await state.clear()
        return
    
    # Сохраняем рекомендации в состоянии
    await state.update_data(
        recommendations=[item.id for item in recommendations],
        recommendations_data={item.id: item for item in recommendations},
        current_index=0,
        recommendations_shown=0
    )
    
    # Показываем первую рекомендацию
    await show_recommendation(message, state, recommendations[0])

async def show_recommendation(message: types.Message, state: FSMContext, media_item: MediaItem):
    """Показ рекомендации"""
    # Эмодзи для типа
    type_emoji = {
        "фильм": "🎥", "сериал": "📺", "мультфильм": "🐭", "аниме": "🌸"
    }.get(media_item.type, "🎬")
    
    # Источник данных
    source_emoji = {
        "tmdb": "🎞️", "kinopoisk": "🎬", "kadikama": "💫", "local": "🏠"
    }.get(media_item.source, "📊")
    
    # Формируем сообщение
    message_text = (
        f"{type_emoji} <b>{media_item.title}</b>\n"
        f"{source_emoji} <i>Источник: {media_item.source.upper()}</i>\n\n"
    )
    
    if media_item.original_title and media_item.original_title != media_item.title:
        message_text += f"<b>Оригинальное название:</b> {media_item.original_title}\n"
    
    message_text += (
        f"<b>Тип:</b> {media_item.type.capitalize()}\n"
        f"<b>Год:</b> {media_item.year}\n"
        f"<b>Рейтинг:</b> ⭐ {media_item.rating}/10\n"
    )
    
    if media_item.duration:
        message_text += f"<b>Длительность:</b> {media_item.duration}\n"
    
    if media_item.genres:
        message_text += f"<b>Жанры:</b> {', '.join(media_item.genres)}\n"
    
    if media_item.mood:
        message_text += f"<b>Настроение:</b> {', '.join(media_item.mood)}\n"
    
    message_text += f"\n<b>Описание:</b>\n{media_item.description}\n\n"
    message_text += "Что думаете об этом варианте?"
    
    await message.answer(message_text, 
                        parse_mode="HTML",
                        reply_markup=get_reaction_keyboard())
    
    await state.set_state(UserState.viewing_recommendations)

# Обработка реакции на рекомендацию
@dp.message(UserState.viewing_recommendations)
async def process_reaction(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    current_index = user_data.get("current_index", 0)
    recommendation_ids = user_data.get("recommendations", [])
    recommendations_data = user_data.get("recommendations_data", {})
    recommendations_shown = user_data.get("recommendations_shown", 0)
    
    if not recommendation_ids:
        await message.answer("Произошла ошибка. Попробуйте снова: /start")
        await state.clear()
        return
    
    if message.text == "🎬 Буду смотреть!":
        # Пользователь выбрал фильм
        current_id = recommendation_ids[current_index]
        media_item = recommendations_data.get(current_id)
        
        if media_item:
            await message.answer(
                f"🎉 Отличный выбор!\n\n"
                f"<b>{media_item.title}</b> - прекрасный вариант для вечера!\n\n"
                f"Приятного просмотра! 🍿\n\n"
                f"Если захотите подобрать что-то ещё - нажмите /start",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove()
            )
        
        # Сохраняем историю просмотров (в реальном проекте - в БД)
        logger.info(f"User selected: {media_item.title if media_item else 'Unknown'}")
        await state.clear()
        return
    
    elif message.text == "➡️ Следующий вариант":
        # Следующий вариант
        recommendations_shown += 1
        await state.update_data(recommendations_shown=recommendations_shown)
        
        # Проверяем лимит в 3 показа
        if recommendations_shown >= 3:
            await message.answer(
                "🤔 Вы точно хотите посмотреть что-то сегодня?",
                reply_markup=get_confirm_restart_keyboard()
            )
            await state.set_state(UserState.confirming_restart)
            return
        
        # Следующий индекс
        next_index = (current_index + 1) % len(recommendation_ids)
        await state.update_data(current_index=next_index)
        
        next_id = recommendation_ids[next_index]
        media_item = recommendations_data.get(next_id)
        
        if media_item:
            await show_recommendation(message, state, media_item)
        else:
            await message.answer("Ошибка при загрузке следующего варианта. Попробуйте /start")
            await state.clear()
    
    else:
        await message.answer("Пожалуйста, используйте кнопки для ответа!")

# Подтверждение перезапуска
@dp.message(UserState.confirming_restart)
async def process_restart_confirmation(message: types.Message, state: FSMContext):
    if message.text == "Да, ищу дальше!":
        # Начинаем показ заново
        user_data = await state.get_data()
        recommendation_ids = user_data.get("recommendations", [])
        
        if recommendation_ids:
            await state.update_data(
                current_index=0,
                recommendations_shown=0
            )
            
            first_id = recommendation_ids[0]
            media_item = user_data.get("recommendations_data", {}).get(first_id)
            
            if media_item:
                await message.answer(
                    "Отлично! Продолжаем поиск с теми же параметрами:",
                    reply_markup=ReplyKeyboardRemove()
                )
                await show_recommendation(message, state, media_item)
            else:
                await message.answer("Ошибка. Попробуйте начать заново: /start")
                await state.clear()
    
    elif message.text == "Нет, не сегодня":
        await message.answer(
            "😔 Похоже, мы с вами не смогли в этот раз подобрать что-то подходящее.\n\n"
            "Не расстраивайтесь! Возможно, в другой раз настроение будет другим.\n\n"
            "Если всё же решите посмотреть что-то - просто нажмите /start",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()
    
    else:
        await message.answer("Пожалуйста, используйте кнопки для ответа!")

# Обработка неизвестных сообщений
@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(
        "Я не понимаю эту команду. 😕\n\n"
        "Используйте /start чтобы начать подбор рекомендаций\n"
        "Или /help для получения справки"
    )

# Запуск бота
async def main():
    """Основная функция запуска"""
    print("="*60)
    print("🎬 Кинобот запущен!")
    print("📱 Перейдите в Telegram и найдите вашего бота")
    print("="*60)
    
    try:
        await dp.start_polling(bot)
    finally:
        # Закрываем сессию API клиента
        await api_client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")