"""Resolve inclusive periods using observed values, without interpreting URL queries."""
from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PeriodError(ValueError):
    """User-facing period error without personal values."""


def _mapping(value, allowed, label):
    if type(value) is not dict or any(type(k) is not str or k not in allowed for k in value):
        raise PeriodError(f'{label}: Provide a mapping containing only allowed keys.')
    return value.copy()


def _date(value, label):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise PeriodError(f'{label}: Provide a string in YYYY-MM-DD format.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PeriodError(f'{label}: Specify a valid date.') from None


def normalize_report(report):
    """Validate structure and types. page_selection requires observations at runtime."""
    report = _mapping(report, {'page', 'kind', 'period'}, 'report')
    page = report.get('page', 'usage')
    kind = report.get('kind', 'detailed')
    if type(page) is not str or type(kind) is not str or (page, kind) not in {
        ('usage', 'detailed'), ('usage', 'summarized'), ('ai_usage', 'ai_usage')
    }:
        raise PeriodError('report: Specify detailed/summarized for usage, or explicit ai_usage for ai_usage.')
    period = _mapping(report.get('period', {}),
        {'mode', 'start_date', 'end_date', 'reference_date', 'timezone'}, 'report.period')
    mode = period.get('mode', 'page_selection')
    if type(mode) is not str or mode not in {'page_selection', 'previous_month', 'current_month', 'custom'}:
        raise PeriodError('report.period.mode: Specify a supported period mode.')
    tz = period.get('timezone', 'UTC')
    if type(tz) is not str or not tz or tz.startswith('/') or '..' in tz.split('/'):
        raise PeriodError('report.period.timezone: Specify an IANA timezone.')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise PeriodError('report.period.timezone: Specify an available IANA timezone.') from None
    if 'reference_date' in period:
        _date(period['reference_date'], 'reference_date')
    if mode == 'custom':
        start = _date(period.get('start_date'), 'start_date')
        end = _date(period.get('end_date'), 'end_date')
        _check_bounds(start, end, kind)
    elif 'start_date' in period or 'end_date' in period:
        raise PeriodError('report.period: Specify explicit start and end dates only with custom.')
    period.update(mode=mode, timezone=tz)
    return {'page': page, 'kind': kind, 'period': period}


def _check_bounds(start, end, kind):
    if start > end:
        raise PeriodError('Period: start date must not be after end date.')
    if kind in {'detailed', 'ai_usage'}:
        if (end - start).days + 1 > 31:
            raise PeriodError('Period: detailed/ai_usage must span at most 31 days, inclusive.')
    else:
        # A leap-day year runs through the following February. Use a calendar year, not a fixed 365 days.
        if start.year == 9999:
            return
        anniversary = date(start.year + 1, start.month, 1) + timedelta(days=start.day - 1)
        if end >= anniversary:
            raise PeriodError('Period: summarized must span at most 1 year, inclusive.')


def resolve_period(report, observed_start=None, observed_end=None, now=None):
    """Return resolved ISO start/end/reference dates and timezone for persistence on resume.

    now is a timezone-aware datetime, defaulting to current UTC time. The current month
    ends at the reference date, capped at today in UTC. Reject future months/observed/explicit periods.
    """
    report = normalize_report(report)
    period = report['period']
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise PeriodError('now: Provide a timezone-aware datetime.')
    utc_today = now.astimezone(timezone.utc).date()
    local_today = now.astimezone(ZoneInfo(period['timezone'])).date()
    reference = _date(period['reference_date'], 'reference_date') if 'reference_date' in period else local_today
    if 'reference_date' in period and reference > local_today:
        raise PeriodError('reference_date: The date must not be later than today in the configured timezone.')
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
            raise PeriodError('Period: specify a reference date whose previous month is representable.') from None
        start = end.replace(day=1)
    else:
        start = reference.replace(day=1)
        end = min(reference, utc_today)
    _check_bounds(start, end, report['kind'])
    if end > utc_today:
        raise PeriodError('Period: dates after today in UTC cannot be retrieved.')
    return {'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'reference_date': reference.isoformat(), 'timezone': period['timezone']}
