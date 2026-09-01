#!/usr/bin/env python
import sys
import os
import json
import openpyxl
import re

GROUPS = [str(i) for i in range(144, 162)]
DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']

# Actual data row ranges for each day, taken directly from this workbook's
# own per-day sheets (Понедельник/Вторник/.../Суббота), whose cells are
# formulas like ='На неделю'!A40 pointing at the exact source rows. Every
# day has 11 period rows (0-я through 10-я пара) starting right after its
# header row - including a "0-я пара" (8:05) row that is usually blank
# (Friday is the one day that actually uses it, for an early PE class).
# NOTE: this used to start each day's range at the first row that *had
# text*, which silently skipped that blank 0-я пара row and shifted every
# later lesson one period earlier than it really is (e.g. a 9:00 class
# was mislabeled as 8:05). Fixed by anchoring to header_row + 1, matching
# the workbook's own formulas exactly.
_HEADER_ROWS = {
    'Понедельник': 3,
    'Вторник': 15,
    'Среда': 27,
    'Четверг': 39,
    'Пятница': 51,
    'Суббота': 64,
}
DAY_DATA_ROWS = {day: (header + 1, header + 11) for day, header in _HEADER_ROWS.items()}

# Plain (start, end) pairs per physical spreadsheet row - no "(N пара)"
# label baked in, since the label gets stripped from messages anyway and
# a lesson spanning two rows needs its own start/end recomputed (see
# parse_schedule), not a fixed per-row label.
_STANDARD_WEEKDAY_SLOTS = [
    ('8:05', '8:50'),
    ('9:00', '9:45'),
    ('9:55', '10:40'),
    ('10:50', '11:35'),
    ('11:45', '12:30'),
    ('12:50', '13:35'),
    ('13:55', '14:40'),
    ('14:50', '15:35'),
    ('15:45', '16:30'),
]

TIME_SLOTS = {
    'Понедельник': _STANDARD_WEEKDAY_SLOTS,
    'Вторник': _STANDARD_WEEKDAY_SLOTS,
    'Среда': _STANDARD_WEEKDAY_SLOTS,
    'Четверг': _STANDARD_WEEKDAY_SLOTS,
    'Пятница': _STANDARD_WEEKDAY_SLOTS,
    'Суббота': [
        ('7:40', '8:20'),
        ('8:30', '9:15'),
        ('9:30', '10:15'),
        ('10:30', '11:15'),
        ('11:30', '12:15'),
        ('12:35', '13:20'),
        ('13:40', '14:25'),
        ('14:40', '15:25'),
        ('15:40', '16:25'),
        ('16:35', '17:55'),
    ],
}


TEACHER_PATTERN = re.compile(r'^[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.?$')
# Just a surname (no initials) - used to recognize one side of a
# slash-joined multi-teacher continuation row, e.g. "Ануфриева/Степанова"
# for split-subgroup lessons like "Пр.инф.2/Ин.в пр.1 31/43".
SURNAME_ONLY_PATTERN = re.compile(r'^[А-ЯЁ][а-яё]+$')
# Room: 2-3 digits at end of string, optionally with (subgroup), but not time patterns like 8.05 or fractions like 31/43
ROOM_PATTERN = re.compile(r'(?<!\d[./])\b(\d{2,3})(?:\([^)]+\))?\b(?![./]\d)')


def clean_text(text):
    if text is None:
        return ''
    text = str(text).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def is_teacher_name(text):
    text = clean_text(text)
    if not text:
        return False
    if TEACHER_PATTERN.match(text):
        return True
    # Multi-teacher continuation row for split-subgroup lessons, e.g.
    # "Ануфриева/Степанова" (no room/subgroup digits, just surnames
    # separated by "/"). A subject row with "/" always carries digits
    # (room or subgroup numbers), so requiring no digits here keeps this
    # from misfiring on subject text.
    if '/' in text and not any(ch.isdigit() for ch in text):
        parts = [p.strip() for p in text.split('/')]
        if parts and all(SURNAME_ONLY_PATTERN.match(p) for p in parts):
            return True
    return False


def extract_room_and_subgroup(text):
    text = clean_text(text)
    # Look for room at the end of the string, optionally with subgroup in parentheses
    # Pattern: digits (2-3) optionally followed by optional space and (subgroup), at end of string
    match = re.search(r'(?<!\d[./])(\d{2,3})\s*(?:\(([^)]+)\))?(?![./]\d)\s*$', text)
    if match:
        room = match.group(1)
        subgroup = match.group(2) if match.group(2) else None
        floor = room[0] if room else ''
        return room, floor, subgroup
    return None, None, None


def remove_room_from_lesson(text):
    text = clean_text(text)
    text = re.sub(r'\s+(?<!\d[./])\d{2,3}\s*(?:\([^)]+\))?(?![./]\d)\s*$', '', text)
    return text


def parse_schedule(excel_path):
    print(f'Читаю файл: {excel_path}')
    wb = openpyxl.load_workbook(excel_path, data_only=False)
    ws = wb.worksheets[2]  # Лист1

    schedule = {group: {day: [] for day in DAYS} for group in GROUPS}

    for day_name, (start_row, end_row) in DAY_DATA_ROWS.items():
        time_slots = TIME_SLOTS[day_name]
        row_idx = 0

        for row_num in range(start_row, end_row + 1):
            if row_idx >= len(time_slots):
                break

            time_slot = time_slots[row_idx]

            for group_idx, group in enumerate(GROUPS):
                col = group_idx + 1  # Columns A-R (1-18)

                cell_value = ws.cell(row=row_num, column=col).value
                lesson_raw = clean_text(cell_value)

                if not lesson_raw or lesson_raw in ['=RIGHT', '#REF!', '--------------------------------']:
                    continue

                # Check if this is a teacher name (continuation of previous lesson).
                # A subject that spans 2 spreadsheet rows is one 90-minute
                # "пара" (double period): the first row is the subject, the
                # second row is the teacher name occupying the *next* time
                # slot. So the real duration runs from the first row's start
                # time to the second row's end time - not just the first
                # row's short 45-minute window.
                if is_teacher_name(lesson_raw):
                    if schedule[group][day_name]:
                        last_lesson = schedule[group][day_name][-1]
                        last_lesson['teacher'] = lesson_raw
                        last_lesson['is_pair'] = True
                        last_lesson['time'] = f"{last_lesson['_start']} - {time_slot[1]}"
                    continue

                # This is a subject/lesson
                room, floor, subgroup = extract_room_and_subgroup(lesson_raw)
                lesson_clean = remove_room_from_lesson(lesson_raw)

                lesson_data = {
                    'time': f'{time_slot[0]} - {time_slot[1]}',
                    '_start': time_slot[0],
                    'subject': lesson_clean,
                }
                if room:
                    lesson_data['cabinet'] = room
                    lesson_data['floor'] = floor
                if subgroup:
                    lesson_data['subgroup'] = subgroup

                schedule[group][day_name].append(lesson_data)

            row_idx += 1

    # Drop the internal bookkeeping field used only to compute pair time spans
    for group in GROUPS:
        for day in DAYS:
            for lesson in schedule[group][day]:
                lesson.pop('_start', None)

    return schedule


def save_schedule(schedule, output_path='schedule.json'):
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    print(f'Расписание сохранено в {output_path}')


def print_summary(schedule):
    total_lessons = 0
    for group in GROUPS:
        group_lessons = sum(len(schedule[group][day]) for day in DAYS)
        total_lessons += group_lessons
        if group_lessons > 0:
            print(f'  Группа {group}: {group_lessons} занятий')
    print(f'\nВсего занятий: {total_lessons}')


def main():
    if len(sys.argv) < 2:
        print('Использование: перетащите .xlsx файл на этот скрипт')
        print('   Или запустите: python update_schedule.py "путь/к/файлу.xlsx"')
        return

    excel_path = sys.argv[1]

    if not os.path.exists(excel_path):
        print(f'Файл не найден: {excel_path}')
        return

    if not excel_path.lower().endswith('.xlsx'):
        print('Файл должен быть .xlsx')
        return

    try:
        schedule = parse_schedule(excel_path)
        save_schedule(schedule)
        print_summary(schedule)
        print('\nГотово! Теперь можно запускать бота.')

        # Print sample
        print('\n--- Пример для группы 144 ---')
        for day in DAYS:
            lessons = schedule['144'][day]
            if lessons:
                print(f'  {day}:')
                for l in lessons[:3]:
                    parts = [f'{l["time"]}: {l["subject"]}']
                    if 'cabinet' in l:
                        cab = f'Кабинет: {l["cabinet"]}'
                        if 'floor' in l:
                            cab += f', Этаж: {l["floor"]}'
                        parts.append(cab)
                    if 'subgroup' in l:
                        parts.append(f'Подгруппа: {l["subgroup"]}')
                    if 'teacher' in l:
                        parts.append(f'Преподаватель: {l["teacher"]}')
                    if l.get('is_pair'):
                        parts.append('(Пара)')
                    print(f'    {" | ".join(parts)}')

    except Exception as e:
        print(f'Ошибка: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()