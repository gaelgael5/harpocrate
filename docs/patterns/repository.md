# Repository

## Probleme
Le code metier contient des requetes SQL directes, couplant la logique applicative au schema de la base. Changer le schema ou la source de donnees impose de modifier le code metier partout.

## Solution
Abstraire l'acces aux donnees derriere des fonctions ou classes dediees. Le code metier appelle `db_get_phase()` sans savoir si ca vient de PostgreSQL, d'un cache Redis, ou d'un fichier JSON.

## Exemple
```python
from asyncpg import Connection

async def db_get_phase(conn: Connection, project_id: int,
                       phase_id: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM project.phases WHERE project_id=$1 AND phase_id=$2",
        project_id, phase_id
    )
    return dict(row) if row else None

async def db_create_next_group(conn: Connection, phase_id: int,
                                group_id: str, agents: list[str]) -> int:
    return await conn.fetchval(
        """INSERT INTO project.groups (phase_id, group_id, agents, status)
           VALUES ($1, $2, $3, 'pending') RETURNING id""",
        phase_id, group_id, agents
    )

async def db_update_deliverable_status(conn: Connection, deliverable_id: int,
                                        status: str) -> None:
    await conn.execute(
        "UPDATE project.deliverables SET status=$1 WHERE id=$2",
        status, deliverable_id
    )

# Code metier — zero SQL, uniquement des appels repository
phase = await db_get_phase(conn, project_id, "discovery")
group_id = await db_create_next_group(conn, phase["id"], "A", ["analyst"])
```

## Quand l'utiliser
- Centraliser et reutiliser les requetes SQL (eviter la duplication)
- Tester le code metier sans base reelle (mock du repository)
- Changer de source de donnees sans impact sur le code metier
- Nommer les operations de maniere explicite (`db_get_pending_tasks` vs SQL brut)

## Quand ne PAS l'utiliser
- Requete unique utilisee a un seul endroit (l'indirection n'apporte rien)
- ORM complet deja en place (SQLAlchemy fournit deja cette abstraction)
