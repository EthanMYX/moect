"""Streaming Excel output with exact IDs, safe strings and lossless long messages."""
import xlsxwriter

EXCEL_ROWS = 1048576


def text_parts(value):
    parts, current, units = [], [], 0
    for character in str(value):
        width = 2 if ord(character) > 65535 else 1
        if units + width > 32700:
            parts.append(''.join(current))
            current, units = [], 0
        current.append(character)
        units += width
    parts.append(''.join(current))
    return parts


def write_excel(path, messages, title, prepare, progress, cancel):
    count, sheet_number, row = 0, 0, EXCEL_ROWS
    sheet = None
    workbook = xlsxwriter.Workbook(str(path), {'constant_memory': True, 'tmpdir': str(path.parent),
                                             'strings_to_formulas': False, 'strings_to_urls': False})
    workbook.use_zip64()
    try:
        heading = workbook.add_format({'bold': True, 'bg_color': '#ECE6FA', 'text_wrap': True})
        content = workbook.add_format({'text_wrap': True, 'valign': 'top', 'num_format': '@'})
        for message in messages:
            cancel()
            text, attachments = prepare(message)
            parts = text_parts(text)
            for number, part in enumerate(parts, 1):
                if row >= EXCEL_ROWS:
                    if sheet is not None:
                        sheet.autofilter(0, 0, row - 1, 9)
                    sheet_number += 1
                    sheet = workbook.add_worksheet('聊天记录_' + str(sheet_number))
                    sheet.freeze_panes(1, 0)
                    sheet.set_column(0, 0, 22)
                    sheet.set_column(1, 4, 23)
                    sheet.set_column(5, 5, 80)
                    sheet.set_column(6, 8, 38)
                    sheet.set_column(9, 9, 12)
                    sheet.write_row(0, 0, ['时间', '会话', '发送者', '发送者 UID', '消息类型', '内容', '消息 ID', '附件路径', '资源说明', '内容分段'], heading)
                    row = 1
                values = [message.get('time_str', ''), title, message.get('sender', ''), message.get('sender_wxid', ''),
                          message.get('type_name') or message.get('kind', ''), part, str(message.get('server_id') or ''),
                          attachments, message.get('resource_notice', ''), str(number) + '/' + str(len(parts))]
                for column, value in enumerate(values):
                    # Explicit string writes also prevent formula/link inference.
                    sheet.write_string(row, column, str(value)[:32700], content)
                row += 1
            count += 1
            if count % 200 == 0:
                progress(count)
        if not sheet_number:
            sheet = workbook.add_worksheet('聊天记录_1')
            sheet.write_row(0, 0, ['时间', '会话', '发送者', '发送者 UID', '消息类型', '内容', '消息 ID', '附件路径', '资源说明', '内容分段'], heading)
        else:
            sheet.autofilter(0, 0, row - 1, 9)
        cancel()
    finally:
        if hasattr(messages, 'close'):
            messages.close()
        workbook.close()
    return count
