"""Tests for parsers.parsers.nmap (System B NmapParser) — Category: parser"""

from parsers.parser import Parser
from parsers.parsers.nmap import NmapParser

# Sample nmap XML outputs for testing

_SINGLE_OPEN_PORT = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames>
      <hostname name="server.example.com"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="http" product="nginx" version="1.24.0" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

_MULTIPLE_PORTS = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="192.168.1.1" addrtype="ipv4"/>
    <hostnames>
      <hostname name="gateway.local"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="ssh" method="table" conf="3"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="https" product="OpenSSL" version="3.0.2" method="table" conf="3"/>
      </port>
      <port protocol="tcp" portid="8080">
        <state state="filtered" reason="no-response"/>
        <service name="http-proxy" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

_MULTIPLE_HOSTS = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames>
      <hostname name="web.example.com"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="http" method="table" conf="3"/>
      </port>
    </ports>
  </host>
  <host>
    <address addr="10.0.0.2" addrtype="ipv4"/>
    <hostnames>
      <hostname name="db.example.com"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="5432">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="postgresql" product="PostgreSQL" version="15.4" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

_NO_OPEN_PORTS = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames>
      <hostname name="firewalled.example.com"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="filtered" reason="no-response"/>
        <service name="ssh" method="table" conf="3"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="closed" reason="reset"/>
        <service name="http" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

_NO_HOSTNAME = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="3306">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="mysql" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

_SERVICE_WITH_EXTRAINFO = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames/>
    <ports>
      <port protocol="tcp" portid="443">
        <state state="open" reason="syn-ack" reason_ttl="64"/>
        <service name="https" product="Apache" version="2.4.57" extrainfo="mod_ssl" method="table" conf="3"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


class TestNmapParser:
    """Tests for NmapParser — direct instantiation."""

    def test_parse_single_open_port(self):
        parser = NmapParser()
        findings = parser.parse(_SINGLE_OPEN_PORT)
        assert len(findings) == 1

        f = findings[0]
        assert f["type"] == "OPEN_PORT"
        assert f["severity"] == "INFO"
        assert f["endpoint"] == "10.0.0.1:80"
        assert f["tool"] == "nmap"
        assert f["confidence"] == 0.90

        ev = f["evidence"]
        assert ev["host"] == "10.0.0.1"
        assert ev["hostname"] == "server.example.com"
        assert ev["port"] == "80"
        assert ev["protocol"] == "tcp"
        assert ev["state"] == "open"
        assert ev["service"] == "http"
        assert ev["product"] == "nginx"
        assert ev["version"] == "1.24.0"

    def test_parse_multiple_ports_skips_filtered(self):
        """Only open ports should be reported — filtered ports are skipped."""
        parser = NmapParser()
        findings = parser.parse(_MULTIPLE_PORTS)
        assert len(findings) == 2  # 22/tcp and 443/tcp open; 8080/tcp filtered

        ports = {f["endpoint"] for f in findings}
        assert "192.168.1.1:22" in ports
        assert "192.168.1.1:443" in ports
        assert "192.168.1.1:8080" not in ports

    def test_parse_multiple_hosts(self):
        parser = NmapParser()
        findings = parser.parse(_MULTIPLE_HOSTS)
        assert len(findings) == 2

        hosts = {f["evidence"]["host"] for f in findings}
        assert "10.0.0.1" in hosts
        assert "10.0.0.2" in hosts

    def test_parse_no_open_ports(self):
        parser = NmapParser()
        findings = parser.parse(_NO_OPEN_PORTS)
        assert findings == []

    def test_parse_empty_output(self):
        parser = NmapParser()
        assert parser.parse("") == []

    def test_parse_whitespace_only(self):
        parser = NmapParser()
        assert parser.parse("   \n  \n  ") == []

    def test_parse_malformed_xml(self):
        parser = NmapParser()
        assert parser.parse("not valid xml") == []

    def test_parse_no_hostname(self):
        """Ports without hostnames should still produce findings."""
        parser = NmapParser()
        findings = parser.parse(_NO_HOSTNAME)
        assert len(findings) == 1
        assert findings[0]["evidence"]["hostname"] == ""

    def test_parse_service_with_extrainfo(self):
        parser = NmapParser()
        findings = parser.parse(_SERVICE_WITH_EXTRAINFO)
        assert len(findings) == 1
        ev = findings[0]["evidence"]
        assert ev["service"] == "https"
        assert ev["product"] == "Apache"
        assert ev["version"] == "2.4.57"
        assert ev["extrainfo"] == "mod_ssl"

    def test_parse_has_title(self):
        parser = NmapParser()
        findings = parser.parse(_SINGLE_OPEN_PORT)
        assert len(findings) == 1
        assert "title" in findings[0]
        assert "Open port:" in findings[0]["title"]


class TestNmapParserRegistry:
    """Test that NmapParser is auto-discovered by the Parser registry."""

    def test_nmap_registered(self):
        p = Parser()
        assert "nmap" in p.parsers
        assert isinstance(p.parsers["nmap"], NmapParser)

    def test_parse_nmap_through_main(self):
        p = Parser()
        findings = p.parse("nmap", _SINGLE_OPEN_PORT)
        assert len(findings) == 1
        assert findings[0]["tool"] == "nmap"
        assert findings[0]["endpoint"] == "10.0.0.1:80"

    def test_parse_nmap_through_main_multiple_ports(self):
        p = Parser()
        findings = p.parse("nmap", _MULTIPLE_PORTS)
        assert len(findings) == 2

    def test_parse_nmap_through_main_empty(self):
        p = Parser()
        findings = p.parse("nmap", "")
        assert findings == []
