"""GET /api/clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["clients"])


@router.get("/clients", response_model=schemas.ClientsResponse)
async def list_clients(ctx: AppContext = Depends(get_context)) -> schemas.ClientsResponse:
    operator = ctx.lease.operator
    clients = [schemas.ClientInfo(**c) for c in ctx.ws.clients_info(operator)]
    return schemas.ClientsResponse(clients=clients, operator_client_id=operator, count=len(clients))
