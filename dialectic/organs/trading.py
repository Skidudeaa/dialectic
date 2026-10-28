"""Today's trading organ. Imports stay lazy to avoid the tools/prompt cycle."""
from fastapi import APIRouter

name = "trading"
room_router = APIRouter()


def tools(room, db):
    from llm.tools import _build_trading_tools
    return _build_trading_tools(room)


def base_identity():
    from llm.prompts import PromptBuilder
    return PromptBuilder.BASE_IDENTITY


def public_identity():
    return dict(organ=name, name="Dialectic", participant="Dialectic", lede=None)


def register_jobs(scheduler):
    from scheduler import Job
    from trading_watch import trading_reconcile, trading_freshness_watchdog
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
    scheduler.register(Job("trading_reconcile", 900, trading_reconcile))
    scheduler.register(Job("trading_freshness_watchdog", 1800, trading_freshness_watchdog))
    for register in (register_brief_jobs, register_news_jobs,
                     register_question_round_jobs, register_round_close_jobs,
                     register_house_forecast_jobs, register_sweep_jobs,
                     register_wire_jobs, register_rss_wire_jobs,
                     register_congress_watch_jobs, register_prediction_watch_jobs,
                     register_reading_echo_jobs, register_field_inference_jobs,
                     register_world_signal_jobs, register_world_watch_jobs):
        register(scheduler)


def routers():
    from api.thesis_relay import router as thesis
    from api.trading_relay import router as trading
    return [(thesis, {}), (trading, {}), (room_router, {})]
