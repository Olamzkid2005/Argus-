> **Current-status notice (verified 2026-09-01):** This document is a dated decision, plan, audit, or historical record. Its completion claims are not a current implementation guarantee; current source, configuration, and tests are authoritative.

# PostgreSQL Volume Cleanup

After a botched database initialization, the named `postgres_data` volume
retains the broken state. Wipe it with:

```bash
docker compose down -v
```

This removes all containers AND the postgres_data volume.

To verify cleanup:
```bash
docker volume ls | grep postgres_data
# Should show no results after `docker compose down -v`
```
