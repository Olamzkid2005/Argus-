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
