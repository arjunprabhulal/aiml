# Sessions in the docs assistant

Each caller gets one ADK session, stored by the session service. A new `run_live()` call on the
same session replays its saved history to a new Live API session.
Create a fresh `LiveRequestQueue` for every `run_live()` call; a closed queue ends the next run at once.
Session resumption reconnects with a cached handle, at most 5 failed attempts in a row.
