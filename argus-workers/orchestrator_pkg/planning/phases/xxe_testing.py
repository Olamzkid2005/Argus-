"""Phase: xxe_testing — _activate_xxe_testing and _xxe_testing_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)

# XML processing libraries and technologies for tech_stack matching
_XML_PROCESSORS: set[str] = {
    # Core C/C++ libraries
    "libxml", "libxml2", "xmlsec",
    # Python
    "lxml", "xml.etree", "xml.dom", "xml.sax", "xml.parsers",
    "defusedxml", "xmltodict", "untangle", "xmlschema",
    # Java
    "javax.xml", "org.w3c.dom", "org.xml.sax",
    "documentbuilder", "documentbuilderfactory",
    "saxparser", "saxparserfactory",
    "xerces", "xalan", "jaxb", "jaxp", "jdom", "dom4j",
    "castor", "xmlbeans",
    # .NET
    "system.xml", "xmltextreader", "xmlreader",
    "xmldocument", "xpathdocument", "linq to xml",
    # PHP
    "simplexml", "domdocument", "xmlwriter",
    "soapclient", "simplexmlelement",
    # Ruby
    "nokogiri", "rexml", "libxml-ruby", "ox",
    # JavaScript / TypeScript
    "xmldom", "xpath", "sax-js", "node-xml",
    "fast-xml-parser", "xml2js",
    # HTTP/SOAP
    "soap", "soapui", "xml-rpc", "wsdl",
    # Frameworks with XML processing
    "spring-web-services", "cxf", "axis",
}


def _activate_xxe_testing(rc) -> tuple[bool, str]:
    """Activate when XML processing libraries are detected in tech_stack.

    XML External Entity (XXE) injection occurs when XML parsers are
    configured to process external entities, allowing attackers to:
    - Read local files (/etc/passwd, config files) via entity references
    - Perform SSRF by referencing internal URLs
    - Denial of Service via Billion Laughs / entity expansion

    Activates when:
      - ``has_xxe`` flag is set on ReconContext (forward-compatible)
      - ``xml_endpoints`` list is populated (forward-compatible)
      - XML processing keywords appear in tech_stack
      - File upload is present (XML file upload vector)
      - API endpoints are present (SOAP/XML APIs)
      - Parameter-bearing URLs are present (XXE injection vector)
    """
    # Forward-compatible: check for dedicated XXE attribute
    has_xxe = _get_attr(rc, "has_xxe", False)
    if has_xxe:
        return True, "XXE signals detected in recon"

    xml_eps = _get_attr(rc, "xml_endpoints", [])
    if xml_eps and len(xml_eps) > 0:
        return True, f"{len(xml_eps)} XML endpoint(s) found"

    # Check tech_stack for XML processing keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _XML_PROCESSORS if kw in tech_lower]
        if matched:
            return True, f"XML processing library detected: {', '.join(matched[:3])}"

    # File upload can include XML files
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload present — XML file upload is an XXE vector"

    # API endpoints may use XML (SOAP, XML-RPC)
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — XML/SOAP endpoints may be vulnerable to XXE"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — XXE testing recommended"

    # Parameter-bearing URLs as XXE vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential XXE vector"

    return False, "no XML processing or XXE signals detected"


def _xxe_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for XXE vulnerability testing.

    Tests for:
      - Classic XXE (file disclosure via external entities)
      - Blind XXE (out-of-band exfiltration via DTD)
      - XXE via SOAP/XML-RPC endpoints
      - XXE via file upload (SVG, XML, DOCX)
      - XXE with SSRF chaining (internal port scanning)
      - Billion Laughs / entity expansion DoS detection
      - Parameter entity injection
      - XInclude attack detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="XXE vulnerability scanning (classic, blind, OOB, file disclosure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "xxe,xml,oob,exposure,disclosure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="XXE with SSRF chaining and entity injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "xxe,ssrf,oast,injection,xinclude"],
        ),
    ]
    return tools
