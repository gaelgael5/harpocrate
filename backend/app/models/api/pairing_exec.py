"""DTOs pour le WebSocket pairing exec — référence de la trame d'ouverture côté client.

Les frames sont JSON. Le backend ne fait pas de validation Pydantic stricte sur la
trame d'ouverture pour ne pas dépendre du framework (raison historique : les
WebSocket FastAPI ne s'intègrent pas avec un body parser BaseModel). On parse
manuellement avec un dict.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class ExecOpenFrameDocker(TypedDict, total=False):
    type: Literal["open_docker"]
    from_step_idx: int


class ExecOpenFrameNative(TypedDict, total=False):
    type: Literal["open_native"]
    username: str
    auth_type: Literal["password", "privkey"]
    password: str
    private_key: str
    passphrase: str
    from_step_idx: int
