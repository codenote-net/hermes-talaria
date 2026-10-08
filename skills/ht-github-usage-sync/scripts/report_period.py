"""包含期間を確定する。URLのクエリは解釈せず、観測値だけを使う。"""
from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PeriodError(ValueError):
    """利用者に公開できる、個人値を含まない期間エラー。"""


def _mapping(value, allowed, label):
    if type(value) is not dict or any(type(k) is not str or k not in allowed for k in value):
        raise PeriodError(f'{label}: 許可されたキーだけのマッピングを指定してください。')
    return value.copy()


def _date(value, label):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise PeriodError(f'{label}: YYYY-MM-DD形式の文字列を指定してください。')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PeriodError(f'{label}: 有効な日付を指定してください。') from None


def normalize_report(report):
    """構造・型を検証する。page_selection の観測は実行時に必要。"""
    report = _mapping(report, {'page', 'kind', 'period'}, 'report')
    page = report.get('page', 'usage')
    kind = report.get('kind', 'detailed')
    if type(page) is not str or type(kind) is not str or (page, kind) not in {
        ('usage', 'detailed'), ('usage', 'summarized'), ('ai_usage', 'ai_usage')
    }:
        raise PeriodError('report: usageにはdetailed/summarized、ai_usageには明示的なai_usageを指定してください。')
    period = _mapping(report.get('period', {}),
        {'mode', 'start_date', 'end_date', 'reference_date', 'timezone'}, 'report.period')
    mode = period.get('mode', 'page_selection')
    if type(mode) is not str or mode not in {'page_selection', 'previous_month', 'current_month', 'custom'}:
        raise PeriodError('report.period.mode: 対応する期間モードを指定してください。')
    tz = period.get('timezone', 'UTC')
    if type(tz) is not str or not tz or tz.startswith('/') or '..' in tz.split('/'):
        raise PeriodError('report.period.timezone: IANAタイムゾーンを指定してください。')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise PeriodError('report.period.timezone: 利用可能なIANAタイムゾーンを指定してください。') from None
    if 'reference_date' in period:
        _date(period['reference_date'], 'reference_date')
    if mode == 'custom':
        start = _date(period.get('start_date'), 'start_date')
        end = _date(period.get('end_date'), 'end_date')
        _check_bounds(start, end, kind)
    elif 'start_date' in period or 'end_date' in period:
        raise PeriodError('report.period: 明示的な開始日・終了日はcustomで指定してください。')
    period.update(mode=mode, timezone=tz)
    return {'page': page, 'kind': kind, 'period': period}


def _check_bounds(start, end, kind):
    if start > end:
        raise PeriodError('期間: 開始日は終了日以前にしてください。')
    if kind in {'detailed', 'ai_usage'}:
        if (end - start).days + 1 > 31:
            raise PeriodError('期間: detailed/ai_usageは両端を含め31日以内にしてください。')
    else:
        # 閏日の1年間は翌年2月末まで。固定365日ではなく暦年を使う。
        if start.year == 9999:
            return
        anniversary = date(start.year + 1, start.month, 1) + timedelta(days=start.day - 1)
        if end >= anniversary:
            raise PeriodError('期間: summarizedは両端を含め1年以内にしてください。')


def resolve_period(report, observed_start=None, observed_end=None, now=None):
    """確定したISO開始日/終了日/基準日/timezoneを返す（再開時に保存可能）。

    nowはタイムゾーン付きdatetime。省略時は現在UTC時刻。現在月は基準日まで、
    ただしUTCの今日を超えない。未来の月/観測/明示期間は拒否する。
    """
    report = normalize_report(report)
    period = report['period']
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise PeriodError('now: タイムゾーン付きdatetimeを指定してください。')
    utc_today = now.astimezone(timezone.utc).date()
    local_today = now.astimezone(ZoneInfo(period['timezone'])).date()
    reference = _date(period['reference_date'], 'reference_date') if 'reference_date' in period else local_today
    if 'reference_date' in period and reference > local_today:
        raise PeriodError('reference_date: 設定タイムゾーンの今日より後の日付は指定できません。')
    mode = period['mode']
    if mode == 'page_selection':
        start = _date(observed_start, 'observed_start')
        end = _date(observed_end, 'observed_end')
    elif mode == 'custom':
        start = _date(period['start_date'], 'start_date')
        end = _date(period['end_date'], 'end_date')
    elif mode == 'previous_month':
        try:
            end = reference.replace(day=1) - timedelta(days=1)
        except OverflowError:
            raise PeriodError('期間: 前月を表現できる基準日を指定してください。') from None
        start = end.replace(day=1)
    else:
        start = reference.replace(day=1)
        end = min(reference, utc_today)
    _check_bounds(start, end, report['kind'])
    if end > utc_today:
        raise PeriodError('期間: UTCの今日より後の日付は取得できません。')
    return {'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'reference_date': reference.isoformat(), 'timezone': period['timezone']}
