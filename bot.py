import html
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

GROUPS = [str(i) for i in range(144, 162)]
DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']

DAY_EMOJI = {
    'Понедельник': '📘',
    'Вторник': '📗',
    'Среда': '📙',
    'Четверг': '📕',
    'Пятница': '📓',
    'Суббота': '📔',
}

DIVIDER = '┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈'

SCHEDULE_FILE = 'schedule.json'
BOT_TOKEN_FILE = 'bot_token.txt'


def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {group: {day: [] for day in DAYS} for group in GROUPS}


def load_token():
    if os.path.exists(BOT_TOKEN_FILE):
        with open(BOT_TOKEN_FILE, 'r') as f:
            return f.read().strip()
    return None


SCHEDULE = load_schedule()


def get_group_keyboard():
    keyboard = []
    row = []
    for i, group in enumerate(GROUPS):
        row.append(InlineKeyboardButton(group, callback_data=f'group_{group}'))
        if len(row) == 6 or i == len(GROUPS) - 1:
            keyboard.append(row)
            row = []
    keyboard.append([InlineKeyboardButton('❌ Отмена', callback_data='cancel')])
    return InlineKeyboardMarkup(keyboard)


def get_day_keyboard(group):
    keyboard = []
    for day in DAYS:
        keyboard.append([InlineKeyboardButton(day, callback_data=f'day_{group}_{day}')])
    keyboard.append([InlineKeyboardButton('🔙 Назад к группам', callback_data='back_to_groups')])
    keyboard.append([InlineKeyboardButton('❌ Отмена', callback_data='cancel')])
    return InlineKeyboardMarkup(keyboard)


def format_schedule(group, day):
    lessons = SCHEDULE.get(group, {}).get(day, [])
    emoji = DAY_EMOJI.get(day, '📅')
    header = f'{emoji}  <b>Группа {html.escape(group)} — {html.escape(day)}</b>'

    if not lessons:
        return f'{header}\n\n😌 <i>Занятий нет — можно отдыхать.</i>'

    blocks = []
    for lesson in lessons:
        time = html.escape(lesson.get('time', ''))
        subject = html.escape(lesson.get('subject', lesson.get('lesson', '')))

        block_lines = [
            f'🕐 <b>{time}</b>',
            f'📚 <b>{subject}</b>',
        ]

        if 'cabinet' in lesson:
            cab_line = f'🚪 каб. {html.escape(str(lesson["cabinet"]))}'
            if 'floor' in lesson:
                cab_line += f' · {html.escape(str(lesson["floor"]))} этаж'
            block_lines.append(cab_line)
        if 'teacher' in lesson:
            block_lines.append(f'👨\u200d🏫 <i>{html.escape(lesson["teacher"])}</i>')

        blocks.append('\n'.join(block_lines))

    body = f'\n{DIVIDER}\n'.join(blocks)
    return f'{header}\n\n{body}'


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '👋 <b>Привет! Я бот расписания ВГАТК.</b>\n\n'
        '🎓 Выбери свою группу:',
        reply_markup=get_group_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == 'cancel':
        await query.edit_message_text('Отменено.')
        return

    if data == 'back_to_groups':
        await query.edit_message_text(
            '🎓 Выбери свою группу:',
            reply_markup=get_group_keyboard()
        )
        return

    if data.startswith('group_'):
        group = data.split('_')[1]
        context.user_data['selected_group'] = group
        await query.edit_message_text(
            f'✅ <b>Группа {html.escape(group)}</b> выбрана.\n📆 Теперь выбери день недели:',
            reply_markup=get_day_keyboard(group),
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith('day_'):
        parts = data.split('_')
        group = parts[1]
        day = '_'.join(parts[2:])

        text = format_schedule(group, day)
        keyboard = [
            [InlineKeyboardButton('🔙 Назад к дням', callback_data=f'group_{group}')],
            [InlineKeyboardButton('🔙 Назад к группам', callback_data='back_to_groups')],
        ]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
        return


def main():
    token = load_token()
    if not token:
        print(f'❌ Токен не найден! Создай файл {BOT_TOKEN_FILE} с токеном бота.')
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print('Bot started...')
    app.run_polling()


if __name__ == '__main__':
    main()