"""Local HTTP/WebSocket API onto the engine.

The only package that knows about FastAPI. It translates requests into calls on
the core services and results into DTOs (``api/schemas.py``); it contains no
business logic. See API_CONTRACT.md.
"""
