"""Local HTTP/WebSocket API bridge onto the Study Bot engine.

This package is the only place that knows about FastAPI/Starlette. It
translates transport requests into calls on the existing `StudyBotApp`
services (`SessionService`, `CourseService`) and translates results back
into transport DTOs (`api/schemas.py`) — it must never contain course/chat/
mode business logic itself. See API_CONTRACT.md for the full contract.
"""
