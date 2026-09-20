from typing import NoReturn

from fastapi import HTTPException

from ..services.errors import ConflictError, ExternalServiceError, SystemBusyError


def raise_for_service_error(exc: Exception) -> NoReturn:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, SystemBusyError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ExternalServiceError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise exc
