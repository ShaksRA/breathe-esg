# TRADEOFFS.md — Breathe ESG

Three things I deliberately did not build, with clear rationale. These aren't gaps from running out of time — they're scoped cuts with explicit reasoning.

---

## 1. Role-based action enforcement (RBAC)

**What I built:** Every API endpoint requires authentication. All authenticated users can read and write.

**What I didn't build:** The `OrganisationMembership.role` field exists (`admin`, `analyst`, `auditor`) and is returned by the `/api/auth/me/` endpoint, but the view layer does not check it. An `auditor` user can currently approve or reject records, which they shouldn't be able to.

**Why I cut it:**

Real RBAC in Django requires wrapping every view in a permission check or permission class, and the exact rules aren't agreed. Three plausible RBAC schemes exist for this domain:

- **Simple (admin/analyst/auditor):** Analysts can review records; auditors are read-only; admins can unlock. Clean to implement but probably too coarse — what if the sustainability lead wants to approve but not edit?
- **Scoped by record state:** Anyone can flag pending records; only analysts can approve; admins can unlock locked records. Behaviour changes based on what the record is, not just who the actor is.
- **Configurable per-org:** Some enterprise clients have a 4-stage approval process (analyst → manager → finance → board sign-off). This can't be hardcoded.

Building the simplest version (case 1) takes a day. Building it wrong creates a false sense of security. Rather than ship RBAC that the PM will immediately ask me to change, I documented the design space and left the hooks in place (the `role` field, the `locked` check in model methods, the `AuditLog` capturing the actor). The next increment is clear.

**How to add it:** DRF custom permissions class checking `request.user.memberships.first().role` against an action whitelist. Two hours of work once the PM confirms the permission model.

---

## 2. Emission factor versioning

**What I built:** Emission factors are in `settings.EMISSION_FACTORS` — a static dict. Every record stores `emission_factor` (the numeric value used) and `emission_factor_source` (the string "DEFRA 2023"). You can see which factor was applied to any record.

**What I didn't build:** A database-backed `EmissionFactor` model that tracks versions over time, with a UI for importing new factor sets and a batch recomputation job to re-derive `co2e_kg` from stored `quantity_normalized` when factors update.

**Why I cut it:**

DEFRA publishes updated factors in June each year. In a production system, when DEFRA 2024 drops, a client needs to decide: do they restate 2023 figures under new factors (for comparability)? Or keep 2023 figures under 2023 factors (for auditability)? This is an accounting policy question, not a technical one. Different clients will answer differently.

A versioned factor table is maybe 3 models and a management command, but the update workflow (who triggers recomputation, does it require a new approval round, does it invalidate locked records?) involves policy decisions I don't have answers to.

The current design doesn't foreclose this. `quantity_normalized` and `unit_normalized` are stored on every record, so a recomputation batch job is one queryset update away once the factor table exists.

**Cost of cutting it:** If DEFRA 2024 factors drop before the client's year-end submission, someone has to manually update the settings dict and re-run the seed. Not acceptable in production; acceptable for a 4-day prototype.

---

## 3. Async ingestion with task queue

**What I built:** File upload runs `run_ingestion(batch)` synchronously before returning an HTTP response. A 200-row SAP export takes ~50ms. The API returns the batch status in the same response.

**What I didn't build:** A Celery task queue with Redis broker, a worker process, and a frontend that polls `/api/batches/{id}/` for status updates.

**Why I cut it:**

Async ingestion is the right architecture for production. A real client SAP export could be 50,000 rows. Running that synchronously in a web worker will hit Gunicorn's timeout and give the user a 503. But adding proper async means:

- Redis (or RabbitMQ) as a broker — another infrastructure piece
- A Celery worker process — another process to manage, deploy, monitor
- A polling or WebSocket mechanism on the frontend so the user sees progress
- Error handling for zombie tasks, retries, idempotency

That's a full week of work that doesn't demonstrate the domain logic at all. The ingestion service is already structured as a pure function with no HTTP dependencies:

```python
def run_ingestion(batch: UploadBatch):
    ...
```

Moving it to async requires exactly one change:

```python
# views.py — current
run_ingestion(batch)

# views.py — async
run_ingestion_task.delay(str(batch.id))
```

And adding this task definition:

```python
@shared_task
def run_ingestion_task(batch_id):
    batch = UploadBatch.objects.get(id=batch_id)
    run_ingestion(batch)
```

The design anticipates this. The view already checks `batch.status` after calling ingestion and the frontend shows batch processing status. The wire-up is left as an obvious next step, not a hidden debt.

**Cost of cutting it:** For the demo data (16 SAP rows, 14 utility rows, 14 travel rows), synchronous ingestion completes in milliseconds. There's no observable difference. For a real deployment it would need to be addressed before go-live.
