"""The Long Way's five hooks. Repository configuration fails closed at boot."""
name = "longway"
LEDE = "Go far enough to be surprised. Stay long enough to understand. Leave room to be changed."


from .tools import build_tools as tools


def base_identity():
    from .identity import scout_identity
    return scout_identity()


def public_identity():
    return dict(organ=name, name="The Long Way", participant="Scout", lede=LEDE)


def register_jobs(scheduler):
    from .jobs import register_jobs as register
    register(scheduler)


def routers():
    from .api import router
    return [(router, {})]


def startup(pool):
    from .register import get_register
    from .api import set_db_pool
    from .search import configuration
    configuration()
    get_register()
    base_identity()
    set_db_pool(pool)
