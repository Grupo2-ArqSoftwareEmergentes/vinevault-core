# Vinevault Core

## Run safely

- **Startup mutates data, including in production:** `app/main.py` seeds factory devices, deletes edges outside `EDGE_DEVICE_SEEDS`, resets the two seeded credentials and reactivates those edges. Use disposable databases for startup checks; tests bypass this lifespan.
- Use Python 3.11 and `python -m pip install -r requirements.txt`. In PowerShell, `.\venv\Scripts\python.exe` can be used without activating the virtualenv.
- From this repository: `docker compose -f docker-compose-test.yml up -d --wait` starts PostgreSQL only, not tests. Before starting against existing data, back up, stop API instances and run `python -m alembic upgrade head`; then `python run.py` serves `app.main:app` on 8000 with reload.
- `docker compose -f docker-compose-prod.yml up --build` also starts the API. Do not run both core stacks together: database container names and host port 5432 collide. Neither includes Kafka; REST-only work can set `KAFKA_BOOTSTRAP_SERVERS=`. For events, the sibling `../vinevault-edge/docker-compose.yml` supplies a localhost broker.
- `.env` loads through `app/core/config.py`; nonempty `DATABASE_URL` overrides the component settings, even compose's `DATABASE_HOST=db`. PostgreSQL access is asyncpg: `postgresql://` is converted, URL query parameters are stripped, and TLS uses `DATABASE_SSL=true`, not `sslmode`.
- Alembic uses the same URL/TLS builders but does not execute app seeds. Its migrations require an online connection, backfill OWNER memberships, and abort on orphan legacy owners. Startup schema checks/`create_all` are not migrations; destructive downgrades are blocked. See `docs/space-tenancy.md`.

## Verification

- Use unittest: `python -B -m unittest discover -s tests -v`. Set `TEST_DATABASE_URL` to an explicit `postgresql+asyncpg://` URL; DB cases otherwise **skip**. They create/drop unique temporary schemas and require schema-creation privileges, not an empty public schema. No CI or lint/typecheck configuration is present.
- Focus quota concurrency: `python -B -m unittest discover -s tests -p test_resource_quotas.py -k concurrent -v`. AI-only checks: `python -B -m unittest discover -s tests -p test_inventory_intelligence.py -v`; no running DB/key is needed and Google is mocked.
- `PostgresAPITestCase` in `tests/test_personal_context.py` grants **10 extra spaces and cavas** in fixtures. Override both allowances to `0` for default-quota tests, as `ResourceQuotaTests` does; do not mistake fixture capacity for product defaults.
- API contracts are in `/openapi.json` and `/docs`. IAM login uses form fields `username` and `password`, not JSON. `/api/v1/iam/health` does not verify Kafka delivery.

## Wiring and boundaries

- `app/main.py` owns routers, ORM imports, seeds and Kafka/outbox lifecycle; `app/dependencies.py` is the composition root. `device` also owns organizations, spaces, thresholds and alerts. Other contexts use `interfaces/acl.py`/`applications/acl.py` facades; IAM has a flatter router/CRUD layout.
- All ORM contexts share `app.core.database.Base`. Register new models in context `models/__init__.py` and check imports in both startup and `migrations/env.py`; missing registration can omit tables from metadata.
- Several concrete device handlers live in `app/device/applications/command_handlers/__init__.py`, not separate leaf files.
- Creation/onboarding commits organization if needed, FREE/ACTIVE space, OWNER membership and default cellar together. `default_wine_cellar` is returned only by creation. UoWs own the request transaction, which guard reads may already have opened; their repositories use `auto_commit=False`.
- `authorize_space_request` is attached to user routers in `app/main.py` and resolves indirect cellar/device/body IDs. Authorization comes from `space_members`, never legacy owner fields or IAM superuser status. Keep new tenant routes guarded; role matrix: `docs/space-tenancy.md`.
- Space deletion rejects assigned devices and atomically deletes inventories, cellars and space. Keep explicit bulk deletion for existing FKs without cascade; per-cellar helpers can commit early and break rollback.
- Quotas count OWNER spaces, not all memberships; purchased extras can repeat FREE purposes. Writers lock account/space **before counting**, with **space -> item** ordering, including Excel and stock exits. Validate before commit; policy is `app/shared/quota_policy.py`, contract is `docs/resource-quotas.md`.
- Quota errors are `403` with structured `detail.code`, not authentication failures. Context `limit: null` means unlimited. Generic renames must not merge stale plan/allowance fields over billing updates.
- Plan prices and limits live in `app/subscriptions/domain/catalog.py`; `quota_policy` reads them. Plans are per **space**, inherited by cellars. Subscription/extra-space POSTs only record `PENDING_PAYMENT` intents and must never grant PRO, allowances, or bypass locks until payment is confirmed server-side.
- Physical inventory column is `wine_inventory_items.name`; `wine_name` remains an ORM/API alias. Optional details/type/age are nullable; omitted updates preserve values, explicit null clears optionals, and Decimal JSON values are strings. Stock history cascades on deletion; absolute PUT/import counts do not create exit records. Contract: `docs/wine-inventory.md`.
- AI stock analysis defaults to JSON; SSE requires `Accept: text/event-stream` or `stream=true`. Empty inventory always returns JSON before initializing Google. Keep SQL input bounded and never retry after emitting text; protocol: `docs/inventory-ai.md`.

## Edge integration

- Consult `edge-core-integration-spec.md` and `core-edge-topic-contract.md` for shared changes; update both services/contracts. Some prose is stale: verify against `app/device/infrastructure/kafka/device_event_publisher.py` and `device_event_consumer.py`.
- Edge -> core uses `Authorization: Bearer <edge_api_key>`, validated against active edges, not a user JWT or local device headers (`X-Hardware-Id`/`X-API-Key`). Preserve provisioning topic `vinevault.provisioning.devices.changed` and fields `device_id`, `hardware_id`, `api_key`, `status`.
- Kafka startup failures are logged and swallowed; a running API/health check is not proof that events work. Verify broker traffic for integration changes.
