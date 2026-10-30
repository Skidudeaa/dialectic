"""The Long Way's five hooks. Repository configuration fails closed at boot."""
name = "longway"
LEDE = "Go far enough to be surprised. Stay long enough to understand. Leave room to be changed."
# The third chair is the Scout. Dialectic's provoker is a philosophy voice that knows no journey.
provoker = False


from .tools import build_tools as tools


def base_identity(room=None):
    from .identity import scout_identity, journey_brief
    if room is not None and room.linked_journey:
        return scout_identity() + "\n\n" + journey_brief(room.linked_journey)
    return scout_identity()


async def room_record_lines(conn, room_id):
    from .proposals import awaiting_lines
    return ("Scout proposals awaiting the Field (unconfirmed: cite the P-id and say so; newest first, ≤15)",
            await awaiting_lines(conn, room_id))


def public_identity():
    return dict(organ=name, name="The Long Way", participant="Scout", lede=LEDE)


def register_jobs(scheduler):
    from .jobs import register_jobs as register
    register(scheduler)


def routers():
    from .api import router, public
    return [(router, {}), (public, {})]


def startup(pool):
    import asyncio
    from .register import get_register
    from .api import set_db_pool
    from .search import configuration
    from .scout import recover
    configuration()
    get_register()
    base_identity()
    set_db_pool(pool)
    # Runs the previous process left 'running' are closed with a receipt, in the background.
    asyncio.get_running_loop().create_task(recover(pool), name="longway-scout-recover")
