#!/usr/bin/env python3
"""
OIC IAR Diff Tool
=================
Compares two Oracle Integration Cloud IAR (Integration ARchive) files or
extracted IAR folders and generates a structured HTML diff report.

Supported input formats:
  - .iar files  (ZIP archives as exported from OIC)
  - Extracted folders  (the 'icspackage/' tree from an unzipped IAR)

Usage:
    python oic_iar_diff.py <iar_v1> <iar_v2> [--output report.html] [--title "My Diff"]
    python oic_iar_diff.py path/to/v1.iar path/to/v2.iar
    python oic_iar_diff.py path/to/v1_folder path/to/v2_folder

Requires: Python 3.7+  (stdlib only — no pip installs needed)
"""

import argparse
import difflib
import html
import io
import json
import os
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OIC_PROJECT_NS    = "http://www.oracle.com/2014/03/ics/project"
OIC_PROJ_DEF_NS   = "http://www.oracle.com/2014/03/ics/project/definition"
OIC_FLOW_DEF_NS   = "http://www.oracle.com/2014/03/ics/flow/definition"
OIC_CONN_NS       = "http://www.oracle.com/2014/03/ics/appinstance"

ICSPACKAGE_PREFIX = "icspackage/"   # normalise paths inside IAR ZIPs


# ---------------------------------------------------------------------------
# IAR Loader
# ---------------------------------------------------------------------------

class IARLoader:
    """Loads an IAR (ZIP file OR extracted folder) into a flat dict of
    relative-path → bytes, always rooted at 'icspackage/'."""

    def __init__(self, path: str):
        self.source = path
        self.files: Dict[str, bytes] = {}
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"IAR source not found: {path}")
        if p.is_file():
            self._load_zip(p)
        else:
            self._load_folder(p)

    def _load_zip(self, p: Path):
        with zipfile.ZipFile(p, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                normalised = name.replace("\\", "/")
                # If ZIP was created from the icspackage/ folder ensure prefix
                if not normalised.startswith(ICSPACKAGE_PREFIX):
                    normalised = ICSPACKAGE_PREFIX + normalised
                self.files[normalised] = zf.read(name)

    def _load_folder(self, p: Path):
        # Walk from the given folder; normalise to icspackage/...
        # Find the 'icspackage' anchor if present
        anchor = p
        if (p / "icspackage").is_dir():
            anchor = p / "icspackage"
            prefix = ICSPACKAGE_PREFIX
        elif p.name == "icspackage":
            anchor = p
            prefix = ICSPACKAGE_PREFIX
        else:
            prefix = ICSPACKAGE_PREFIX  # best guess

        for root, _dirs, files in os.walk(anchor):
            for fname in files:
                full = Path(root) / fname
                rel = full.relative_to(anchor).as_posix()
                key = prefix + rel
                self.files[key] = full.read_bytes()

    # -- Convenience accessors -------------------------------------------

    def text(self, key: str, encoding: str = "utf-8") -> Optional[str]:
        data = self.files.get(key)
        if data is None:
            return None
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            return data.decode("latin-1")

    def keys_matching(self, pattern: str) -> List[str]:
        """Return all keys whose relative path matches a glob-like pattern
        (supports * and **).  Uses simple regex conversion."""
        regex = re.compile(
            "^" + re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
        )
        return sorted(k for k in self.files if regex.match(k))

    def keys_endswith(self, suffix: str) -> List[str]:
        return sorted(k for k in self.files if k.endswith(suffix))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_properties(content: str) -> Dict[str, str]:
    """Parse a Java-style .properties file into a dict."""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
        elif ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def pretty_xml(content: bytes) -> str:
    """Parse and pretty-print an XML document for readable diffing."""
    try:
        root = ET.fromstring(content)
        _indent_xml(root)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError:
        try:
            return content.decode("utf-8")
        except Exception:
            return content.decode("latin-1")


def _indent_xml(elem: ET.Element, level: int = 0):
    """Add pretty-print whitespace to an ElementTree in-place."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def unified_diff_html(a: str, b: str, from_label: str = "v1", to_label: str = "v2") -> str:
    """Return an HTML <table> with a side-by-side diff."""
    differ = difflib.HtmlDiff(wrapcolumn=100)
    return differ.make_table(
        a.splitlines(keepends=True),
        b.splitlines(keepends=True),
        fromdesc=from_label,
        todesc=to_label,
        context=True,
        numlines=3,
    )


def dict_diff(d1: Dict, d2: Dict) -> Dict[str, Tuple[Any, Any]]:
    """Return {key: (v1_val, v2_val)} for keys that differ or were added/removed."""
    all_keys = set(d1) | set(d2)
    result = {}
    for k in sorted(all_keys):
        v1 = d1.get(k)
        v2 = d2.get(k)
        if v1 != v2:
            result[k] = (v1, v2)
    return result


def xml_attrib_dict(el: ET.Element) -> Dict[str, str]:
    """Strip namespace prefixes from attribute names for cleaner comparison."""
    return {re.sub(r"\{[^}]+\}", "", k): v for k, v in el.attrib.items()}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class ChangeSet:
    """Collects changes in a named category."""

    def __init__(self, name: str, icon: str = ""):
        self.name = name
        self.icon = icon
        self.added: List[Dict] = []
        self.removed: List[Dict] = []
        self.modified: List[Dict] = []
        self.unchanged_count: int = 0

    @property
    def total_changes(self):
        return len(self.added) + len(self.removed) + len(self.modified)

    def has_changes(self):
        return self.total_changes > 0

    def add(self, label: str, detail: str = ""):
        self.added.append({"label": label, "detail": detail})

    def remove(self, label: str, detail: str = ""):
        self.removed.append({"label": label, "detail": detail})

    def modify(self, label: str, detail: str = "", diff_html: str = ""):
        self.modified.append({"label": label, "detail": detail, "diff": diff_html})


# ---------------------------------------------------------------------------
# Processor → Activity Name mapping
# ---------------------------------------------------------------------------

def _build_processor_map(loader: IARLoader) -> Dict[str, str]:
    """Parse project.xml and return {processor_NNNN: 'ActivityName'} for every
    flow step that has a named parent activity in the orchestration."""
    proj_keys = [k for k in loader.files if k.endswith("PROJECT-INF/project.xml")]
    if not proj_keys:
        return {}
    try:
        root = ET.fromstring(loader.files[proj_keys[0]])
    except ET.ParseError:
        return {}

    mapping: Dict[str, str] = {}
    for el in root.iter():
        act_name = el.get("name") or el.get("id") or ""
        if not act_name:
            continue
        for child in el:
            ref = child.get("refUri", "")
            # Only direct processor references (no '/' means no sub-path)
            if ref.startswith("processor_") and "/" not in ref:
                mapping.setdefault(ref, act_name)
    return mapping


# ---------------------------------------------------------------------------
# Main Differ
# ---------------------------------------------------------------------------

class IARDiffer:

    def __init__(self, loader1: IARLoader, loader2: IARLoader,
                 label1: str = "v1", label2: str = "v2"):
        self.v1 = loader1
        self.v2 = loader2
        self.label1 = label1
        self.label2 = label2
        self.changesets: List[ChangeSet] = []
        # Build merged processor_NNNN → ActivityName map (v1 takes precedence)
        _map_v2 = _build_processor_map(loader2)
        _map_v1 = _build_processor_map(loader1)
        self._proc_label: Dict[str, str] = {**_map_v2, **_map_v1}

    def run(self) -> List[ChangeSet]:
        self.changesets = [
            self._diff_metadata(),
            self._diff_connections(),
            self._diff_dvms(),
            self._diff_keys(),
            self._diff_project_structure(),
            self._diff_xslt_mappers(),
            self._diff_assignments(),
            self._diff_jca_configs(),
            self._diff_other_files(),
        ]
        return self.changesets

    # -----------------------------------------------------------------------
    # 1. Metadata
    # -----------------------------------------------------------------------

    def _diff_metadata(self) -> ChangeSet:
        cs = ChangeSet("Project Metadata", "📋")
        key = "icspackage/project/"
        # Find the properties file under project/<name>/
        prop_keys_v1 = [k for k in self.v1.files if k.endswith("ics_project_attributes.properties")]
        prop_keys_v2 = [k for k in self.v2.files if k.endswith("ics_project_attributes.properties")]

        if not prop_keys_v1 and not prop_keys_v2:
            return cs

        p1_text = self.v1.text(prop_keys_v1[0]) if prop_keys_v1 else ""
        p2_text = self.v2.text(prop_keys_v2[0]) if prop_keys_v2 else ""
        p1 = parse_properties(p1_text or "")
        p2 = parse_properties(p2_text or "")

        diffs = dict_diff(p1, p2)
        important = {"icscode", "version", "name", "state", "oicVersion",
                     "style", "keywords", "description", "documentationUrl"}
        skip = {"CAV", "mod", "smartTags", "validity", "version",
                "lastUpdatedICSVersion", "originalICSVersion", "project_transient_state",
                "project_version"}

        for k, (v_old, v_new) in diffs.items():
            if k in skip:
                cs.unchanged_count += 1
                continue
            # For comma-separated list properties, compare as sets to ignore order
            if k == "keywords" and v_old is not None and v_new is not None:
                if set(v_old.split(",")) == set(v_new.split(",")):
                    cs.unchanged_count += 1
                    continue
            flag = " ⭐" if k in important else ""
            if v_old is None:
                cs.add(k, f"New value: {v_new}{flag}")
            elif v_new is None:
                cs.remove(k, f"Was: {v_old}{flag}")
            else:
                cs.modify(k, f"{v_old}  →  {v_new}{flag}")

        cs.unchanged_count += len(p1) - len(diffs)
        return cs

    # -----------------------------------------------------------------------
    # 2. Connections (appinstances)
    # -----------------------------------------------------------------------

    def _diff_connections(self) -> ChangeSet:
        cs = ChangeSet("Connections (appinstances)", "🔌")

        conn_v1 = {k: self.v1.text(k) for k in self.v1.keys_matching("icspackage/appinstances/*.xml")}
        conn_v2 = {k: self.v2.text(k) for k in self.v2.keys_matching("icspackage/appinstances/*.xml")}

        # Normalise to basename for matching
        def _basename(key):
            return key.split("/")[-1]

        base_v1 = {_basename(k): k for k in conn_v1}
        base_v2 = {_basename(k): k for k in conn_v2}
        all_bases = set(base_v1) | set(base_v2)

        for base in sorted(all_bases):
            if base not in base_v1:
                cs.add(base, "New connection (not in v1)")
            elif base not in base_v2:
                cs.remove(base, "Removed (not in v2)")
            else:
                cs.unchanged_count += 1

        return cs

    def _conn_field_diff(self, t1: str, t2: str) -> str:
        """Extract meaningful field-level differences from connection XML."""
        try:
            root1 = ET.fromstring(t1)
            root2 = ET.fromstring(t2)
        except ET.ParseError:
            return "XML parse error"

        fields = []
        for el1 in root1.iter():
            tag = re.sub(r"\{[^}]+\}", "", el1.tag)
            el2 = root2.find(f".//{el1.tag}")
            if el2 is not None and el1.text != el2.text:
                v1_val = (el1.text or "").strip()
                v2_val = (el2.text or "").strip()
                if v1_val != v2_val:
                    fields.append(f"<code>{tag}</code>: <del>{html.escape(v1_val)}</del> → <ins>{html.escape(v2_val)}</ins>")
        return " | ".join(fields) if fields else "Binary content changed"

    # -----------------------------------------------------------------------
    # 3. DVMs
    # -----------------------------------------------------------------------

    def _diff_dvms(self) -> ChangeSet:
        cs = ChangeSet("Domain Value Maps (DVMs)", "🗺️")

        dvm_v1 = {k.split("/")[-1]: self.v1.text(k) for k in self.v1.keys_matching("icspackage/dvms/*.dvm")}
        dvm_v2 = {k.split("/")[-1]: self.v2.text(k) for k in self.v2.keys_matching("icspackage/dvms/*.dvm")}
        all_dvms = set(dvm_v1) | set(dvm_v2)

        for dvm in sorted(all_dvms):
            if dvm not in dvm_v1:
                cs.add(dvm, "New DVM")
            elif dvm not in dvm_v2:
                cs.remove(dvm, "Removed DVM")
            else:
                t1, t2 = dvm_v1[dvm] or "", dvm_v2[dvm] or ""
                if t1 != t2:
                    px1 = pretty_xml(t1.encode())
                    px2 = pretty_xml(t2.encode())
                    if px1 == px2:
                        cs.unchanged_count += 1
                    else:
                        row_diff = self._dvm_row_diff(t1, t2)
                        dh = unified_diff_html(px1, px2, self.label1, self.label2)
                        cs.modify(dvm, row_diff, dh)
                else:
                    cs.unchanged_count += 1

        return cs

    def _dvm_row_diff(self, t1: str, t2: str) -> str:
        """High-level row count diff for a DVM."""
        try:
            r1 = ET.fromstring(t1)
            r2 = ET.fromstring(t2)
            rows1 = len(r1.findall(".//{*}row") or r1.findall(".//row"))
            rows2 = len(r2.findall(".//{*}row") or r2.findall(".//row"))
            if rows1 == rows2:
                return f"Row count unchanged ({rows1}) — cell values changed"
            return f"Row count: {rows1} → {rows2} ({rows2 - rows1:+d} rows)"
        except ET.ParseError:
            return "Content changed"

    # -----------------------------------------------------------------------
    # 4. Keys
    # -----------------------------------------------------------------------

    def _diff_keys(self) -> ChangeSet:
        cs = ChangeSet("Cryptographic Keys", "🔑")

        keys_v1 = {k.split("/")[-1]: self.v1.text(k) for k in self.v1.keys_matching("icspackage/keys/*.json")}
        keys_v2 = {k.split("/")[-1]: self.v2.text(k) for k in self.v2.keys_matching("icspackage/keys/*.json")}
        all_keys = set(keys_v1) | set(keys_v2)

        for key in sorted(all_keys):
            if key not in keys_v1:
                cs.add(key, "New key reference")
            elif key not in keys_v2:
                cs.remove(key, "Removed key reference")
            else:
                t1, t2 = keys_v1[key] or "", keys_v2[key] or ""
                if t1 != t2:
                    try:
                        j1, j2 = json.loads(t1), json.loads(t2)
                        diffs = dict_diff(
                            {k: str(v) for k, v in j1.items()},
                            {k: str(v) for k, v in j2.items()},
                        )
                        detail = "; ".join(f"{k}: {ov} → {nv}" for k, (ov, nv) in diffs.items())
                    except Exception:
                        detail = "Content changed"
                    dh = unified_diff_html(t1, t2, self.label1, self.label2)
                    cs.modify(key, detail, dh)
                else:
                    cs.unchanged_count += 1

        return cs

    # -----------------------------------------------------------------------
    # 5. Project Structure (project.xml + analysis.json)
    # -----------------------------------------------------------------------

    def _diff_project_structure(self) -> ChangeSet:
        cs = ChangeSet("Integration Flow Structure", "🔀")

        proj_keys_v1 = [k for k in self.v1.files if k.endswith("PROJECT-INF/project.xml")]
        proj_keys_v2 = [k for k in self.v2.files if k.endswith("PROJECT-INF/project.xml")]

        if not proj_keys_v1 or not proj_keys_v2:
            if proj_keys_v1:
                cs.remove("project.xml", "project.xml missing from v2")
            elif proj_keys_v2:
                cs.add("project.xml", "project.xml only in v2 (new integration)")
            return cs

        raw1 = self.v1.files[proj_keys_v1[0]]
        raw2 = self.v2.files[proj_keys_v2[0]]

        # High-level: parse and extract processors / applications
        p1 = self._parse_project_xml(raw1)
        p2 = self._parse_project_xml(raw2)

        # --- Applications (adapter endpoints) ---
        apps1 = {a["name"]: a for a in p1["applications"]}
        apps2 = {a["name"]: a for a in p2["applications"]}
        all_apps = set(apps1) | set(apps2)
        app_changes = []
        for app in sorted(all_apps):
            if app not in apps1:
                cs.add(f"Application: {app}", f"New adapter endpoint [{apps2[app].get('adapter','')}]")
                app_changes.append(f"+ {app}")
            elif app not in apps2:
                cs.remove(f"Application: {app}", f"Removed [{apps1[app].get('adapter','')}]")
                app_changes.append(f"- {app}")
            else:
                a1, a2 = apps1[app], apps2[app]
                diffs = dict_diff(a1, a2)
                if diffs:
                    detail = "; ".join(f"{k}: {ov}→{nv}" for k,(ov,nv) in diffs.items())
                    cs.modify(f"Application: {app}", detail)
                    app_changes.append(f"~ {app}")
                else:
                    cs.unchanged_count += 1

        # --- Processors (flow steps) ---
        procs1 = {p["name"]: p for p in p1["processors"]}
        procs2 = {p["name"]: p for p in p2["processors"]}
        all_procs = set(procs1) | set(procs2)

        type_counts: Dict[str, Tuple[int,int]] = defaultdict(lambda: [0,0])
        for proc in sorted(all_procs):
            if proc not in procs1:
                cs.add(f"Processor: {proc}", f"New step [{procs2[proc].get('type','')}]")
                type_counts[procs2[proc].get("type","")][1] += 1
            elif proc not in procs2:
                cs.remove(f"Processor: {proc}", f"Removed [{procs1[proc].get('type','')}]")
                type_counts[procs1[proc].get("type","")][0] += 1
            else:
                pr1, pr2 = procs1[proc], procs2[proc]
                diffs = dict_diff(pr1, pr2)
                if diffs:
                    detail = "; ".join(f"{k}: {ov}→{nv}" for k,(ov,nv) in diffs.items())
                    cs.modify(f"Processor: {proc}", detail)
                else:
                    cs.unchanged_count += 1

        # --- Orchestration flow sequence diff ---
        seq1 = p1.get("flow_sequence", [])
        seq2 = p2.get("flow_sequence", [])
        if seq1 != seq2:
            dh = unified_diff_html(
                "\n".join(seq1), "\n".join(seq2), self.label1, self.label2
            )
            cs.modify("Orchestration Flow Order",
                      f"Flow sequence changed ({len(seq1)} steps → {len(seq2)} steps)",
                      dh)

        # Full project.xml raw diff for reference
        px1 = pretty_xml(raw1)
        px2 = pretty_xml(raw2)
        if px1 != px2:
            dh = unified_diff_html(px1, px2, self.label1 + " project.xml", self.label2 + " project.xml")
            cs.modify("project.xml (full diff)", "Complete file diff", dh)

        return cs

    def _parse_project_xml(self, raw: bytes) -> Dict:
        """Extract applications, processors, and flow sequence from project.xml."""
        result = {"applications": [], "processors": [], "flow_sequence": []}
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return result

        # project.xml uses multiple namespaces
        # Flow/adapter elements: http://www.oracle.com/2014/03/ics/flow/definition
        F = OIC_FLOW_DEF_NS
        ns_f = {"f": F}

        # Applications
        for app in root.findall(f".//{{{F}}}application"):
            attribs = xml_attrib_dict(app)
            # Get adapter code from nested <f:adapter><f:code> or <f:adapter code="...">
            adapter_el = app.find(f"{{{F}}}adapter")
            adapter_code = ""
            if adapter_el is not None:
                code_el = adapter_el.find(f"{{{F}}}code")
                adapter_code = (code_el.text if code_el is not None else "") or adapter_el.get("code", "")
            name_el = app.find(f"{{{F}}}name")
            app_name = (name_el.text if name_el is not None else "") or attribs.get("name", attribs.get("code", "?"))
            role_el = app.find(f"{{{F}}}role")
            role = (role_el.text if role_el is not None else "") or attribs.get("role", "")
            mep_el = app.find(f"{{{F}}}mep")
            mep = (mep_el.text if mep_el is not None else "") or attribs.get("mep", "")
            result["applications"].append({
                "name": app_name.strip(),
                "adapter": adapter_code.strip(),
                "role": role.strip(),
                "mep": mep.strip(),
            })

        # Processors
        for proc in root.findall(f".//{{{F}}}processor"):
            attribs = xml_attrib_dict(proc)
            name_el = proc.find(f"{{{F}}}processorName")
            if name_el is None:
                name_el = proc.find(f"{{{F}}}name")
            proc_name = (name_el.text if name_el is not None else "") or attribs.get("name", attribs.get("code", "?"))
            proc_name = proc_name.strip()
            # Resolve processor_NNNN folder names to human-readable activity names
            proc_name = self._proc_label.get(proc_name, proc_name)
            type_el = proc.find(f"{{{F}}}type")
            proc_type = (type_el.text if type_el is not None else "") or attribs.get("type", "")
            result["processors"].append({
                "name": proc_name,
                "type": proc_type.strip(),
                "id": attribs.get("id", ""),
            })

        # Flow sequence — extract named activities in document order from orchestration
        orch = root.find(f".//{{{F}}}orchestration")
        if orch is not None:
            seen = set()
            for child in orch.iter():
                tag = re.sub(r"\{[^}]+\}", "", child.tag)
                name_attr = child.get("name") or child.get("code")
                if name_attr and tag not in ("orchestration", "processors", "applications",
                                              "icsflow", "property", "code", "name"):
                    entry = f"{tag}:{name_attr}"
                    if entry not in seen:
                        seen.add(entry)
                        result["flow_sequence"].append(entry)

        return result

    # -----------------------------------------------------------------------
    # 6. XSLT Mappers
    # -----------------------------------------------------------------------

    def _diff_xslt_mappers(self) -> ChangeSet:
        cs = ChangeSet("XSLT Mapper Transformations", "🔄")

        xsl_v1 = {self._xsl_key(k): (k, self.v1.text(k)) for k in self.v1.keys_endswith(".xsl")}
        xsl_v2 = {self._xsl_key(k): (k, self.v2.text(k)) for k in self.v2.keys_endswith(".xsl")}

        # Exclude scheduledOrc/ (system-generated)
        xsl_v1 = {k: v for k, v in xsl_v1.items() if "scheduledOrc" not in k}
        xsl_v2 = {k: v for k, v in xsl_v2.items() if "scheduledOrc" not in k}

        all_xsl = set(xsl_v1) | set(xsl_v2)
        for key in sorted(all_xsl):
            if key not in xsl_v1:
                path = xsl_v2[key][0]
                cs.add(key, f"New mapper: {path}")
            elif key not in xsl_v2:
                path = xsl_v1[key][0]
                cs.remove(key, f"Removed mapper: {path}")
            else:
                t1, t2 = xsl_v1[key][1] or "", xsl_v2[key][1] or ""
                if t1 != t2:
                    # Extract only the template body (after the schema header)
                    body1 = self._xsl_template_body(t1)
                    body2 = self._xsl_template_body(t2)
                    # Normalise whitespace before comparing so that line-ending
                    # and indentation-only changes don't produce phantom diffs.
                    if body1.split() == body2.split():
                        cs.unchanged_count += 1
                    else:
                        dh = unified_diff_html(body1, body2, self.label1, self.label2)
                        added, removed = self._xsl_mapping_diff(t1, t2)
                        detail_parts = []
                        if added:
                            detail_parts.append(f"<ins>+{len(added)} mapping(s)</ins>")
                        if removed:
                            detail_parts.append(f"<del>-{len(removed)} mapping(s)</del>")
                        if not detail_parts:
                            detail_parts = ["Expression(s) changed"]
                        cs.modify(key, " ".join(detail_parts), dh)
                else:
                    cs.unchanged_count += 1

        return cs

    def _xsl_key(self, full_path: str) -> str:
        """Create a human-readable key for an XSL file.
        Replaces the processor_NNNN segment with the parent activity name."""
        parts = full_path.split("/")
        for i, seg in enumerate(parts):
            if seg.startswith("processor_"):
                label = self._proc_label.get(seg, seg)
                return label + "/" + "/".join(parts[i + 1:])
        return parts[-1]

    def _xsl_template_body(self, xsl: str) -> str:
        """Extract the xsl:template content, skipping the oracle-xsl-mapper header."""
        # Find xsl:template match="/"
        match = re.search(r"<xsl:template[^>]+match=\"/\"", xsl)
        if match:
            return xsl[match.start():]
        return xsl

    def _xsl_mapping_diff(self, t1: str, t2: str) -> Tuple[List[str], List[str]]:
        """Return (added_elements, removed_elements) by comparing element/attribute paths."""
        def _extract_elements(xsl: str) -> set:
            return set(re.findall(r"<(?:xsl:element|xsl:attribute)\s+name=\"([^\"]+)\"", xsl))
        e1, e2 = _extract_elements(t1), _extract_elements(t2)
        return sorted(e2 - e1), sorted(e1 - e2)

    # -----------------------------------------------------------------------
    # 7. Assignment Expressions (expr.properties)
    # -----------------------------------------------------------------------

    def _diff_assignments(self) -> ChangeSet:
        cs = ChangeSet("Assignment Expressions", "✏️")

        expr_v1 = {self._proc_key(k): self.v1.text(k)
                   for k in self.v1.keys_endswith("expr.properties")}
        expr_v2 = {self._proc_key(k): self.v2.text(k)
                   for k in self.v2.keys_endswith("expr.properties")}

        all_expr = set(expr_v1) | set(expr_v2)
        for key in sorted(all_expr):
            if key not in expr_v1:
                t2 = expr_v2[key] or ""
                p2 = parse_properties(t2)
                var = p2.get("VariableName", key.split("/")[-1])
                cs.add(f"{var} [{key}]", f"Expr: {p2.get('XpathExpression', p2.get('TextExpression', ''))[:120]}")
            elif key not in expr_v2:
                t1 = expr_v1[key] or ""
                p1 = parse_properties(t1)
                var = p1.get("VariableName", key.split("/")[-1])
                cs.remove(f"{var} [{key}]", f"Was: {p1.get('XpathExpression', p1.get('TextExpression', ''))[:120]}")
            else:
                t1, t2 = expr_v1[key] or "", expr_v2[key] or ""
                if t1 != t2:
                    p1, p2 = parse_properties(t1), parse_properties(t2)
                    var = p1.get("VariableName", p2.get("VariableName", key.split("/")[-1]))
                    diffs = dict_diff(p1, p2)
                    if not diffs:
                        cs.unchanged_count += 1
                    else:
                        details = []
                        for dk, (dv1, dv2) in diffs.items():
                            details.append(f"<b>{dk}</b>:<br><del>{html.escape(str(dv1 or ''))}</del><br><ins>{html.escape(str(dv2 or ''))}</ins>")
                        dh = unified_diff_html(t1, t2, self.label1, self.label2)
                        cs.modify(f"{var} [{key}]", "<br>".join(details), dh)
                else:
                    cs.unchanged_count += 1

        return cs

    def _proc_key(self, full_path: str) -> str:
        """Create a human-readable key for resource files.
        Replaces processor_NNNN with the parent activity name from project.xml,
        and normalises resourcegroup_NNNN to resourcegroup_N so that keys match
        across versions even when the numeric IDs change."""
        parts = full_path.split("/")
        for i, seg in enumerate(parts):
            if seg.startswith("processor_"):
                label = self._proc_label.get(seg, seg)
                rest = "/".join(parts[i + 1:])
                rest = re.sub(r"resourcegroup_\d+", "resourcegroup_N", rest)
                return label + "/" + rest
            if seg.startswith("application_"):
                return "/".join(parts[i:])
        return full_path

    # -----------------------------------------------------------------------
    # 8. JCA Adapter Configs
    # -----------------------------------------------------------------------

    def _diff_jca_configs(self) -> ChangeSet:
        cs = ChangeSet("JCA Adapter Configurations", "⚙️")

        jca_v1 = {self._app_key(k): self.v1.text(k) for k in self.v1.keys_endswith(".jca")}
        jca_v2 = {self._app_key(k): self.v2.text(k) for k in self.v2.keys_endswith(".jca")}

        all_jca = set(jca_v1) | set(jca_v2)
        for key in sorted(all_jca):
            if key not in jca_v1:
                cs.add(key, "New JCA endpoint config")
            elif key not in jca_v2:
                cs.remove(key, "Removed JCA endpoint config")
            else:
                t1, t2 = jca_v1[key] or "", jca_v2[key] or ""
                if t1 != t2:
                    px1 = pretty_xml(t1.encode())
                    px2 = pretty_xml(t2.encode())
                    if px1 == px2:
                        cs.unchanged_count += 1
                    else:
                        detail = self._jca_field_diff(t1, t2)
                        dh = unified_diff_html(px1, px2, self.label1, self.label2)
                        cs.modify(key, detail, dh)
                else:
                    cs.unchanged_count += 1

        return cs

    def _app_key(self, full_path: str) -> str:
        parts = full_path.split("/")
        for i, seg in enumerate(parts):
            if seg.startswith("processor_"):
                label = self._proc_label.get(seg, seg)
                rest = "/".join(parts[i + 1:])
                rest = re.sub(r"resourcegroup_\d+", "resourcegroup_N", rest)
                return label + "/" + rest
            if seg.startswith("application_"):
                rest = "/".join(parts[i:])
                rest = re.sub(r"application_\d+", "application_N", rest)
                rest = re.sub(r"inbound_\d+", "inbound_N", rest)
                rest = re.sub(r"resourcegroup_\d+", "resourcegroup_N", rest)
                return rest
        return full_path

    def _jca_field_diff(self, t1: str, t2: str) -> str:
        """Extract meaningful property differences from JCA XML."""
        try:
            r1, r2 = ET.fromstring(t1), ET.fromstring(t2)
        except ET.ParseError:
            return "XML parse error"

        def _props(root: ET.Element) -> Dict[str, str]:
            d = {}
            for el in root.iter():
                tag = re.sub(r"\{[^}]+\}", "", el.tag)
                name = el.get("name") or el.get("Name")
                value = el.get("value") or el.get("Value") or el.text
                if name and value:
                    d[f"{tag}.{name}"] = str(value)
                elif el.text and el.text.strip():
                    d[tag] = el.text.strip()
            return d

        p1, p2 = _props(r1), _props(r2)
        diffs = dict_diff(p1, p2)
        if not diffs:
            return "Attribute-level changes"
        parts = []
        for k, (ov, nv) in list(diffs.items())[:8]:
            parts.append(f"<code>{html.escape(k)}</code>: "
                         f"<del>{html.escape(str(ov or ''))}</del> → "
                         f"<ins>{html.escape(str(nv or ''))}</ins>")
        if len(diffs) > 8:
            parts.append(f"… and {len(diffs)-8} more")
        return "<br>".join(parts)

    # -----------------------------------------------------------------------
    # 9. Other / catch-all
    # -----------------------------------------------------------------------

    def _diff_other_files(self) -> ChangeSet:
        cs = ChangeSet("Other Files (WSDL, XSD, etc.)", "📄")

        skip_suffixes = {".xsl", ".jca", ".dvm", ".json", ".properties"}
        skip_patterns = {"appinstances/", "dvms/", "keys/", "scheduledOrc/"}

        def _include(k: str) -> bool:
            if any(k.endswith(s) for s in skip_suffixes):
                return False
            if any(p in k for p in skip_patterns):
                return False
            if k.endswith("project.xml") or k.endswith("analysis.json") or k.endswith("layout.json"):
                return False
            return True

        keys_v1 = {k for k in self.v1.files if _include(k)}
        keys_v2 = {k for k in self.v2.files if _include(k)}

        # Normalise keys for cross-version matching: strip the versioned project
        # folder prefix (icspackage/project/<NAME_VERSION>/resources/) so that
        # paths from v1 and v2 can be compared purely on their content-relative
        # path, then replace remaining numeric IDs.
        def _normalise(k: str) -> str:
            # Drop everything up to and including the first 'resources/' segment
            match = re.search(r"/resources/", k)
            if match:
                k = k[match.end():]
            def _proc_sub(m: re.Match) -> str:
                return self._proc_label.get(m.group(0), "processor_?")
            k = re.sub(r"processor_\d+", _proc_sub, k)
            k = re.sub(r"resourcegroup_\d+", "resourcegroup_N", k)
            k = re.sub(r"application_\d+", "application_N", k)
            k = re.sub(r"inbound_\d+", "inbound_N", k)
            return k

        norm_v1 = defaultdict(list)
        for k in keys_v1:
            norm_v1[_normalise(k)].append(k)
        norm_v2 = defaultdict(list)
        for k in keys_v2:
            norm_v2[_normalise(k)].append(k)

        all_norm = set(norm_v1) | set(norm_v2)
        for nk in sorted(all_norm):
            paths1 = norm_v1.get(nk, [])
            paths2 = norm_v2.get(nk, [])
            if not paths1:
                for p in paths2:
                    cs.add(p.split("/")[-1], f"New file: {p}")
            elif not paths2:
                for p in paths1:
                    cs.remove(p.split("/")[-1], f"Removed: {p}")
            else:
                # Compare first match
                t1 = self.v1.files.get(paths1[0], b"")
                t2 = self.v2.files.get(paths2[0], b"")
                if t1 != t2:
                    fname = paths1[0].split("/")[-1]
                    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    if ext in ("xml", "wsdl", "xsd"):
                        s1 = pretty_xml(t1)
                        s2 = pretty_xml(t2)
                    else:
                        try:
                            s1 = t1.decode("utf-8")
                            s2 = t2.decode("utf-8")
                        except Exception:
                            s1, s2 = repr(t1), repr(t2)
                    if s1 == s2:
                        cs.unchanged_count += 1
                    else:
                        dh = unified_diff_html(s1, s2, self.label1, self.label2)
                        cs.modify(fname, f"{paths1[0]}", dh)
                else:
                    cs.unchanged_count += 1

        return cs


# ---------------------------------------------------------------------------
# HTML Report Generator
# ---------------------------------------------------------------------------

from iar_report_assets import HTMLReporter


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_label(path: str) -> str:
    p = Path(path)
    try:
        loader = IARLoader(path) if p.is_file() else IARLoader(path)
        for k in loader.files:
            if k.endswith("ics_project_attributes.properties"):
                props = parse_properties(loader.text(k) or "")
                name = props.get("project_name", "")
                ver  = props.get("project_version", "")
                if name and ver:
                    return f"{name} v{ver}"
                if name:
                    return name
    except Exception:
        pass
    return p.stem


def main():
    parser = argparse.ArgumentParser(
        description="OIC IAR Diff Tool — compare two Oracle Integration Cloud IAR files or folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("v1", help="Path to first IAR file or extracted folder (baseline)")
    parser.add_argument("v2", help="Path to second IAR file or extracted folder (new version)")
    parser.add_argument("--output", "-o", default="iar_diff_report.html",
                        help="Output HTML report path (default: iar_diff_report.html)")
    parser.add_argument("--title", default="", help="Custom report title")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open the report in a browser after generation")
    args = parser.parse_args()

    print(f"[OIC IAR Diff]  Loading v1: {args.v1}")
    loader1 = IARLoader(args.v1)
    print(f"  → {len(loader1.files)} files loaded")

    print(f"[OIC IAR Diff]  Loading v2: {args.v2}")
    loader2 = IARLoader(args.v2)
    print(f"  → {len(loader2.files)} files loaded")

    label1 = resolve_label(args.v1)
    label2 = resolve_label(args.v2)
    # Use the integration name (without version) as the base report title
    base_name = label1.rsplit(" v", 1)[0] if " v" in label1 else label1
    title = args.title or f"OIC Diff Report: {base_name}"

    print(f"\n[OIC IAR Diff]  Comparing '{label1}' vs '{label2}' ...")
    differ = IARDiffer(loader1, loader2, label1, label2)
    changesets = differ.run()

    print("\n[OIC IAR Diff]  Summary:")
    total_changes = 0
    for cs in changesets:
        if cs.has_changes() or cs.unchanged_count > 0:
            adds = f"+{len(cs.added)}" if cs.added else ""
            rems = f"-{len(cs.removed)}" if cs.removed else ""
            mods = f"~{len(cs.modified)}" if cs.modified else ""
            ok   = f"={cs.unchanged_count}" if cs.unchanged_count else ""
            parts = [x for x in [adds, rems, mods, ok] if x]
            print(f"  {cs.icon} {cs.name:<45} {', '.join(parts)}")
            total_changes += cs.total_changes

    print(f"\n  Total changes: {total_changes}")

    reporter = HTMLReporter(changesets, label1, label2, title)
    report_html = reporter.render()

    out_path = Path(args.output)
    out_path.write_text(report_html, encoding="utf-8")
    print(f"\n[OIC IAR Diff]  Report written to: {out_path.resolve()}")

    if not args.no_browser:
        import webbrowser
        webbrowser.open(out_path.resolve().as_uri())
        print("[OIC IAR Diff]  Opening report in browser...")


if __name__ == "__main__":
    main()
