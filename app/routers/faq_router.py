from aiogram import Router, F, types

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.data.csv_handler import CSVHandler

router = Router()
handler = CSVHandler()


# [key: id -> question,answer]
@router.callback_query(F.data == "handle_questions")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    questions = handler.get_questions()
    if not questions:
        await callback.message.edit_text("Помилка: Файл питань порожній або не знайдений")
        return

    builder = InlineKeyboardBuilder()
    for question in questions:
        callback_str = f"faq_answer_{question['id']}"
        builder.add(
            types.InlineKeyboardButton(
                text=question['question'],
                callback_data=callback_str
            )
        )
    builder.add(
        types.InlineKeyboardButton(
            text="Назад",
            callback_data="controller_hub"
        )
    )
    builder.adjust(1)

    await callback.message.edit_text("Ось найчастіші запитання:\n", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("faq_answer_"))
async def answer_faq(callback: types.CallbackQuery):
    await callback.answer()
    question_id = int(callback.data.split("_")[2])
    answer = handler.get_answer_by_id(question_id)
    if not answer:
        answer = "Ой! На жаль відповідь на це питання не знайдена."

    import re
    
    builder = InlineKeyboardBuilder()

    mono_match = re.search(r'href=["\']?(https://send\.monobank\.ua/[^"\'<\s]+)', answer)
    if mono_match:
        builder.add(
            types.InlineKeyboardButton(
                text="💙 Підтримати збір",
                url=mono_match.group(1)
            )
        )

    yt_match = re.search(r'href=["\']?(https://(?:www\.)?youtube\.com/[^"\'<\s]+)', answer)
    if yt_match:
        builder.add(
            types.InlineKeyboardButton(
                text="📺 YouTube Студради",
                url=yt_match.group(1)
            )
        )

    maps_match = re.search(r'href=["\']?(https://maps\.app\.goo\.gl/[^"\'<\s]+)', answer)
    if maps_match:
        builder.add(
            types.InlineKeyboardButton(
                text="📍 18 корпус на карті",
                url=maps_match.group(1)
            )
        )

    builder.add(
        types.InlineKeyboardButton(
            text="Назад",
            callback_data="handle_questions"
        )
    )
    builder.add(
        types.InlineKeyboardButton(
            text="Головне меню",
            callback_data="controller_hub"
        )
    )

    builder.adjust(1)

    await callback.message.edit_text(
        answer, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML", 
        disable_web_page_preview=True
    )


@router.callback_query(F.data == "more_questions_faq")
async def handle_more_questions(callback: types.CallbackQuery):
    await show_faq(callback)
