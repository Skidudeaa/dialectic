# api/thread_titles.py — what a room's first thread is called.
#
# ONE definition, in its own module rather than in api/main.py, because both
# the generic room-create path and Home's scheme-spawn path write it and a
# router importing the app module would close an import loop.
#
# WHY IT IS NOT "Main": the literal was written in TWO places in create_room —
# the threads row and the THREAD_CREATED event payload — so a placeholder
# nobody chose ended up on all 24 rooms and in the event log behind them. Asked
# what the shared room even was, the owner's answer was "there's a 'main' but
# idk what the fuck that even is." A label naming a thread's position in a list
# teaches nothing.
#
# "The floor" is where you speak. It belongs to the same vocabulary as the
# room's other places — the house, the bench, the record, the ledger — and says
# what the thread is FOR. Branches fork off it and carry their own titles; this
# is only ever the trunk.

ROOT_THREAD_TITLE = "The floor"
