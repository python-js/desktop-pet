"""Recurrences use the UTC offset selected when the schedule was created."""
from datetime import datetime, timedelta

REPEAT_LABELS = {'none': '不重复', 'daily': '每天', 'weekdays': '每周一至五', 'weekly': '每周'}


def validate_repeat(rule):
    if not isinstance(rule, str) or rule not in REPEAT_LABELS:
        raise ValueError('不支持的重复规则')
    return rule


def schedule_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('重复时间缺少时区')
    return result


def next_occurrence(scheduled_at, rule, now):
    validate_repeat(rule)
    if rule == 'none':
        return None
    base = schedule_time(scheduled_at)
    local_now = now.astimezone(base.tzinfo)
    days = max(1, (local_now.date() - base.date()).days)
    if rule == 'weekly':
        days = max(7, ((days + 6) // 7) * 7)
    candidate = base + timedelta(days=days)
    while candidate <= local_now or (rule == 'weekdays' and candidate.weekday() >= 5):
        candidate += timedelta(days=7 if rule == 'weekly' else 1)
    return candidate


def in_period(due, period, now):
    if period == 'all':
        return True
    if period == 'overdue':
        return due < now
    local_due = due.astimezone(now.tzinfo)
    if period == 'today':
        return local_due.date() == now.date()
    if period == 'future':
        return local_due.date() > now.date()
    raise ValueError('不支持的时间筛选')
