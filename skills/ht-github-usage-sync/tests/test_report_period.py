"""月境界・包含日数・UTC可用性の合成テスト。"""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_period import PeriodError, resolve_period

NOW = datetime(2026, 10, 8, 0, 30, tzinfo=timezone.utc)


class PeriodTests(unittest.TestCase):
    def test_page_selection_requires_observation(self):
        with self.assertRaises(PeriodError): resolve_period({}, now=NOW)
        result = resolve_period({}, observed_start='2026-09-01', observed_end='2026-09-30', now=NOW)
        self.assertEqual(result['start_date'], '2026-09-01')
        self.assertEqual(result['end_date'], '2026-09-30')
        self.assertEqual(result['reference_date'], '2026-10-08')
        self.assertEqual(result['timezone'], 'UTC')

    def test_previous_month_year_and_leap(self):
        for ref, start, end in [('2026-01-10', '2025-12-01', '2025-12-31'),
                ('2024-03-01', '2024-02-01', '2024-02-29'),
                ('2025-03-15', '2025-02-01', '2025-02-28')]:
            result = resolve_period({'period': {'mode': 'previous_month', 'reference_date': ref}}, now=NOW)
            self.assertEqual((result['start_date'], result['end_date']), (start, end))

    def test_current_month_utc_availability(self):
        result = resolve_period({'period': {'mode': 'current_month'}}, now=NOW)
        self.assertEqual((result['start_date'], result['end_date']), ('2026-10-01', '2026-10-08'))
        boundary = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)
        result = resolve_period({'period': {'mode': 'current_month', 'timezone': 'America/Los_Angeles'}}, now=boundary)
        self.assertEqual((result['start_date'], result['end_date'], result['reference_date']),
            ('2026-09-01', '2026-09-30', '2026-09-30'))
        boundary = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
        with self.assertRaises(PeriodError):
            resolve_period({'period': {'mode': 'current_month', 'timezone': 'Pacific/Kiritimati'}}, now=boundary)
        with self.assertRaises(PeriodError):
            resolve_period({'period': {'mode': 'custom', 'start_date': '2026-10-01', 'end_date': '2026-10-09'}}, now=NOW)

    def test_explicit_future_reference_rejected_in_all_modes(self):
        for mode in ['current_month', 'previous_month', 'custom', 'page_selection']:
            period = {'mode': mode, 'reference_date': '2026-10-31'}
            if mode == 'custom':
                period.update(start_date='2026-09-01', end_date='2026-09-30')
            with self.subTest(mode=mode):
                with self.assertRaises(PeriodError) as error:
                    resolve_period({'period': period}, observed_start='2026-09-01',
                        observed_end='2026-09-30', now=NOW)
                self.assertNotIn('2026-10-31', str(error.exception))
                self.assertIn('reference_date', str(error.exception))

    def test_explicit_reference_uses_local_today_not_utc_today(self):
        cases = [
            (NOW, 'America/Los_Angeles', '2026-10-07', '2026-10-08', '2026-10-07'),
            (datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc),
                'Pacific/Kiritimati', '2026-10-09', '2026-10-10', '2026-10-08')]
        for now, tz, today, tomorrow, expected_end in cases:
            with self.subTest(timezone=tz):
                period = {'mode': 'current_month', 'timezone': tz, 'reference_date': today}
                result = resolve_period({'period': period}, now=now)
                self.assertEqual(result['reference_date'], today)
                self.assertEqual(result['end_date'], expected_end)
                period['reference_date'] = tomorrow
                with self.assertRaises(PeriodError):
                    resolve_period({'period': period}, now=now)
                del period['reference_date']
                self.assertEqual(resolve_period({'period': period}, now=now), result)

    def test_inclusive_limits_and_summary_calendar_year(self):
        for kind in ['detailed', 'ai_usage']:
            report = {'page': 'ai_usage' if kind == 'ai_usage' else 'usage', 'kind': kind,
                'period': {'mode': 'custom', 'start_date': '2024-01-01', 'end_date': '2024-01-31'}}
            self.assertEqual(resolve_period(report, now=NOW)['end_date'], '2024-01-31')
            report['period']['end_date'] = '2024-02-01'
            with self.assertRaises(PeriodError): resolve_period(report, now=NOW)
        report = {'kind': 'summarized', 'period': {'mode': 'custom', 'start_date': '2024-01-01', 'end_date': '2024-12-31'}}
        resolve_period(report, now=NOW)
        report['period']['end_date'] = '2025-01-01'
        with self.assertRaises(PeriodError): resolve_period(report, now=NOW)
        report['period'].update(start_date='2024-02-29', end_date='2025-02-28')
        resolve_period(report, now=NOW)
        report['period']['end_date'] = '2025-03-01'
        with self.assertRaises(PeriodError): resolve_period(report, now=NOW)

    def test_frozen_custom_bounds(self):
        result = resolve_period({'period': {'mode': 'previous_month'}}, now=NOW)
        report = {'period': {'mode': 'custom', **{k: result[k] for k in ['start_date', 'end_date', 'reference_date', 'timezone']}}}
        self.assertEqual(resolve_period(report, now=datetime(2027, 1, 1, tzinfo=timezone.utc)), result)

    def test_strict_period_schema(self):
        invalid = [{'mode': 'bad'}, {'mode': 'custom'}, {'mode': 'previous_month', 'start_date': '2024-01-01'},
            {'mode': 'page_selection', 'end_date': '2024-01-01'}, {'timezone': 'Invalid/Zone'},
            {'reference_date': True}, {'reference_date': '2024-2-01'}, {'secret': 'x'},
            {'mode': 'custom', 'start_date': '2024-02-30', 'end_date': '2024-03-01'},
            {'mode': 'custom', 'start_date': '2024-03-01', 'end_date': '2024-02-01'}]
        for period in invalid:
            with self.subTest(period=period), self.assertRaises(PeriodError): resolve_period({'period': period}, now=NOW)
        with self.assertRaises(PeriodError): resolve_period({}, observed_start='2026-09-01', now=NOW)
        with self.assertRaises(PeriodError): resolve_period({}, now=datetime(2026, 10, 8))
        with self.assertRaises(PeriodError): resolve_period({'page': 'ai_usage'}, observed_start='2026-09-01', observed_end='2026-09-30', now=NOW)


if __name__ == '__main__': unittest.main()
