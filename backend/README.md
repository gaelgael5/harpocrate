# Harpocrate — Backend

Spec : `docs/specs/OVERVIEW.md` et `docs/specs/LOT_00_FOUNDATIONS.md`.
Roadmap : `docs/superpowers/plans/2026-05-01-harpocrate-roadmap.md`.

## Démarrer en local (Docker)

1. Copier `.env.example` à la racine du repo en `.env`, remplir les variables.
2. Générer une `HARPOCRATE_HMAC_KEY` (32 octets base64) :
   ```bash
   py -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
   ```
3. Démarrer la stack :
   ```bash
   docker compose up -d --build
   ```
4. Appliquer les migrations :
   ```bash
   docker compose exec backend python -m migrations.apply_migrations
   ```
5. Tester :
   ```bash
   curl http://localhost:8000/v1/health
   curl http://localhost:8000/v1/config/public
   curl http://localhost:8000/v1/config/keycloak
   ```

## Tests / lint / typecheck

Depuis `backend/` :

```bash
py -m pip install -e ".[dev]"
py -m pytest -v
py -m ruff check app/ tests/ migrations/
py -m mypy --strict app/ tests/ migrations/
```

## Structure

```
backend/
├── app/
│   ├── api/v1/           # routers FastAPI versionnés
│   ├── core/             # config Pydantic Settings + logging structlog
│   ├── db/               # pool asyncpg
│   ├── models/           # DTOs Pydantic (LOT_02+)
│   ├── services/         # logique métier (LOT_02+)
│   └── crypto/           # utilitaires crypto serveur (LOT_02+)
├── migrations/           # *.sql versionnés + apply_migrations.py
├── tests/                # pytest + pytest-asyncio
├── pyproject.toml
└── Dockerfile            # multi-stage : base / dev / prod
```
