"""Tests for sqlmap dump-data exfiltration parsing and capability probe.

Covers the bounded sqlmap --dump wiring:
- parsers/parsers/sqlmap.py extracts DATA_EXFILTRATION findings from
  sqlmap text dump output (used when the installed sqlmap build rejects
  --output-format=json/--json-output).
- orchestrator_pkg/scan.py capability probe detects whether the installed
  sqlmap accepts the JSON output flags.
"""

from unittest.mock import patch

from parsers.parsers.sqlmap import SqlmapParser


class TestSqlmapDumpParsing:
    SAMPLE_DUMP = """\
[21:47:08] [INFO] testing connection to the target URL http://example.com/page?id=1
[21:47:08] [INFO] heuristics detected web page and 'thankyou' keyword
[21:47:08] [INFO] testing for SQL injection on GET parameter 'id'
[21:47:09] [INFO] GET parameter 'id' is 'Generic UNION query (NULL) - 1 to 20 columns' injectable
sqlmap identified the following injection point(s) with a total of 42 HTTP(s) requests:
---
Parameter: id (GET)
    Type: UNION query
    Title: Generic UNION query (NULL) - 1 to 20 columns
    Payload: id=-7525 UNION ALL SELECT NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL-- -
---
[21:47:10] [INFO] the back-end DBMS is MySQL
[21:47:10] [INFO] fetching database names
[21:47:10] [INFO] fetching tables for database: 'testdb'
[21:47:11] [INFO] fetching columns for table 'users' in database 'testdb'
[21:47:11] [INFO] fetching entries for table 'users' in database 'testdb'
Database: testdb
Table: users
[3 entries]
+----+-------+---------------------+
| id | name  | email               |
+----+-------+---------------------+
| 1  | alice | alice@example.com   |
| 2  | bob   | bob@example.com     |
| 3  | root  | root@example.com    |
+----+-------+---------------------+
[21:47:12] [INFO] fetched data logged to text files under
"""

    def test_dump_produces_data_exfiltration_finding(self):
        findings = SqlmapParser().parse(self.SAMPLE_DUMP)
        exfil = [f for f in findings if f["type"] == "DATA_EXFILTRATION"]
        assert len(exfil) == 1
        f = exfil[0]
        assert f["severity"] == "CRITICAL"
        assert f["confidence"] == 0.95
        assert f["tool"] == "sqlmap"
        assert f["evidence"]["database"] == "testdb"
        assert f["evidence"]["table"] == "users"
        assert f["evidence"]["entry_count"] == 3
        assert len(f["evidence"]["dumped_rows"]) == 3
        assert "alice@example.com" in "".join(f["evidence"]["dumped_rows"])

    def test_endpoint_includes_table_for_dedup(self):
        findings = SqlmapParser().parse(self.SAMPLE_DUMP)
        exfil = [f for f in findings if f["type"] == "DATA_EXFILTRATION"]
        assert exfil[0]["endpoint"].endswith("#testdb.users")

    def test_injection_point_also_emitted(self):
        findings = SqlmapParser().parse(self.SAMPLE_DUMP)
        sqli = [f for f in findings if f["type"] == "SQL_INJECTION"]
        assert len(sqli) == 1
        assert sqli[0]["endpoint"].startswith("http")

    def test_no_dump_no_exfil_finding(self):
        output = (
            "sqlmap identified the following injection point: "
            "https://example.com?id=1"
        )
        findings = SqlmapParser().parse(output)
        assert [f["type"] for f in findings] == ["SQL_INJECTION"]

    def test_multiple_tables_produce_multiple_findings(self):
        output = (
            "Database: db1\n"
            "Table: t1\n"
            "[2 entries]\n"
            "+----+\n"
            "| a  |\n"
            "+----+\n"
            "| x  |\n"
            "+----+\n"
            "Database: db1\n"
            "Table: t2\n"
            "[1 entry]\n"
            "+----+\n"
            "| b  |\n"
            "+----+\n"
            "| y  |\n"
            "+----+\n"
        )
        findings = SqlmapParser().parse(output)
        exfil = [f for f in findings if f["type"] == "DATA_EXFILTRATION"]
        assert len(exfil) == 2
        assert {f["evidence"]["table"] for f in exfil} == {"t1", "t2"}
        # Distinct endpoints per table (pipeline dedups on type|endpoint|tool)
        assert len({f["endpoint"] for f in exfil}) == 2

    def test_header_row_skipped_from_dumped_rows(self):
        output = (
            "Database: db1\n"
            "Table: t1\n"
            "[2 entries]\n"
            "+-----+\n"
            "| col |\n"
            "+-----+\n"
            "| v1  |\n"
            "+-----+\n"
        )
        findings = SqlmapParser().parse(output)
        exfil = [f for f in findings if f["type"] == "DATA_EXFILTRATION"]
        assert len(exfil) == 1
        assert exfil[0]["evidence"]["dumped_rows"] == ["| v1  |"]

    def test_empty_output(self):
        assert SqlmapParser().parse("") == []


class TestSqlmapJsonProbe:
    def test_probe_detects_json_support(self):
        import orchestrator_pkg.scan as scan_mod

        scan_mod._sqlmap_json_support = None
        fake_result = type(
            "R", (), {"stdout": "--output-format=json  Format of the output", "stderr": ""}
        )()
        with patch("subprocess.run", return_value=fake_result):
            assert scan_mod._sqlmap_supports_json() is True

    def test_probe_reports_unsupported_build(self):
        import orchestrator_pkg.scan as scan_mod

        scan_mod._sqlmap_json_support = None
        fake_result = type("R", (), {"stdout": "Usage: sqlmap [options]", "stderr": ""})()
        with patch("subprocess.run", return_value=fake_result):
            assert scan_mod._sqlmap_supports_json() is False

    def test_probe_cached(self):
        import orchestrator_pkg.scan as scan_mod

        scan_mod._sqlmap_json_support = False
        with patch("subprocess.run", side_effect=AssertionError("should not re-run")):
            assert scan_mod._sqlmap_supports_json() is False

    def test_probe_skips_when_sqlmap_absent(self):
        import orchestrator_pkg.scan as scan_mod

        scan_mod._sqlmap_json_support = None
        with patch(
            "tools.tool_utils.resolve_tool_binary", return_value=None
        ), patch("subprocess.run", side_effect=AssertionError("should not spawn")):
            assert scan_mod._sqlmap_supports_json() is False

    def test_probe_uses_resolved_binary(self):
        import orchestrator_pkg.scan as scan_mod

        scan_mod._sqlmap_json_support = None
        fake_result = type("R", (), {"stdout": "", "stderr": "no such option"})()
        with patch(
            "tools.tool_utils.resolve_tool_binary",
            return_value="/custom/sqlmap",
        ), patch("subprocess.run", return_value=fake_result) as run_mock:
            assert scan_mod._sqlmap_supports_json() is False
            run_mock.assert_called_once()
            assert run_mock.call_args[0][0][0] == "/custom/sqlmap"
