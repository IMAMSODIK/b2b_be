from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import ScheduleException, ScheduleRule


def resolve_playlist_id(now_utc: datetime, timezone_name: str, rules: list[ScheduleRule], exceptions: list[ScheduleException]):
    ordered_exceptions = sorted(exceptions, key=lambda x: (-x.priority, str(x.id)))
    for ex in ordered_exceptions:
        if ex.starts_at_utc <= now_utc < ex.ends_at_utc:
            return str(ex.playlist_id), "schedule_exception"

    local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    weekday = local_now.weekday()
    local_time = local_now.time()
    local_date = local_now.date()

    valid_rules: list[ScheduleRule] = []
    for rule in rules:
        if weekday not in rule.days_of_week:
            continue
        if not (rule.start_time <= local_time < rule.end_time):
            continue
        if rule.valid_from and local_date < rule.valid_from:
            continue
        if rule.valid_to and local_date > rule.valid_to:
            continue
        valid_rules.append(rule)

    if not valid_rules:
        return None, "fallback_none"

    valid_rules.sort(key=lambda r: (-r.priority, str(r.id)))
    return str(valid_rules[0].playlist_id), "schedule_rule"
