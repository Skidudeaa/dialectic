"""The default organ preserves the original order, not merely the tool count."""
from organ import active
from llm import tools
from scheduler import Scheduler, SchedulerContext, Job
from trading_watch import scheduler_heartbeat, register_bloodstream_jobs
from tests.conftest import make_room


def test_default_tool_order():
    room=make_room()
    original=tools._build_trading_tools(room)+tools._build_dialectic_tools(room,None)
    if tools._world_tools_enabled():
        original+=tools._build_world_tools(room,None)
    if tools._cairn_tools_enabled():
        original+=tools._build_cairn_tools()
    if tools._workshop_enabled():
        original+=tools._build_workshop_tools(room,None)
    assert active.name == "trading"
    assert tools.build_registry(room,None).names() == [t.name for t in original]


def test_default_jobs_match_original_registration_order():
    from llm.night_shift import register_brief_jobs
    from llm.news_night import register_news_jobs
    from llm.question_round import register_question_round_jobs
    from llm.round_close_watch import register_round_close_jobs
    from llm.house_forecast import register_house_forecast_jobs
    from llm.silence_sweep import register_sweep_jobs
    from llm.wire import register_wire_jobs
    from llm.rss_wire import register_rss_wire_jobs
    from llm.congress_watch import register_congress_watch_jobs
    from llm.prediction_watch import register_prediction_watch_jobs
    from llm.reading_echo import register_reading_echo_jobs
    from llm.field_inference import register_field_inference_jobs
    from world_adapters import register_world_signal_jobs
    from llm.world_watch import register_world_watch_jobs
    from llm.workshop_jobs import register_workshop_jobs
    old=Scheduler(SchedulerContext(None))
    for fn in (register_bloodstream_jobs,register_brief_jobs,register_news_jobs,register_question_round_jobs,
               register_round_close_jobs,register_house_forecast_jobs,register_sweep_jobs,register_wire_jobs,
               register_rss_wire_jobs,register_congress_watch_jobs,register_prediction_watch_jobs,
               register_reading_echo_jobs,register_field_inference_jobs,register_world_signal_jobs,
               register_world_watch_jobs,register_workshop_jobs):
        fn(old)
    new=Scheduler(SchedulerContext(None))
    new.register(Job("scheduler_heartbeat",600,scheduler_heartbeat))
    active.register_jobs(new)
    register_workshop_jobs(new)
    assert [(j.name,j.interval_s,j.enabled_env,j.daily_at,j.daily_tz) for j in new.jobs] == [(j.name,j.interval_s,j.enabled_env,j.daily_at,j.daily_tz) for j in old.jobs]
