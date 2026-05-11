# OIC IAR Diff Tool

A command-line utility that compares two Oracle Integration Cloud (OIC) IAR (Integration ARchive) files or extracted IAR folders and generates a structured, interactive HTML diff report.

---

## Features

- Accepts `.iar` ZIP archives exported from OIC **or** extracted `icspackage/` folder trees
- Produces a single, self-contained HTML report styled with the Oracle Redwood Design System
- Compares the following artifact categories:
  | Category | Description |
  |---|---|
  | **Project Metadata** | `ics_project_attributes.properties` key/value pairs |
  | **Connections** | Adapter endpoint XML files under `appinstances/` |
  | **Domain Value Maps (DVMs)** | `.dvm` files, including row-count changes |
  | **Cryptographic Keys** | JSON key reference files under `keys/` |
  | **Integration Flow Structure** | `project.xml` — applications, processors, and orchestration step order |
  | **XSLT Mapper Transformations** | `.xsl` files, with element-level mapping diff |
  | **Assignment Expressions** | `expr.properties` XPath/text expression changes |
  | **JCA Adapter Configurations** | `.jca` endpoint configuration property diffs |
  | **Other Files** | WSDL, XSD, and any remaining artifacts not covered above |
- Report sections auto-expand when changes are detected; unchanged sections are collapsed
- Side-by-side diff tables are embedded inline and shown on demand
- Numeric internal IDs (`processor_NNNN`, `resourcegroup_NNNN`, etc.) are resolved to human-readable activity names where possible, enabling stable cross-version comparisons

---

## Requirements

- Python 3.7 or later
- **No third-party packages** — uses the Python standard library only

---

## Usage

```bash
# Compare two .iar files
python oic_iar_diff.py path/to/v1.iar path/to/v2.iar

# Compare two extracted IAR folders
python oic_iar_diff.py path/to/v1_folder path/to/v2_folder

# Specify a custom output path and report title
python oic_iar_diff.py v1.iar v2.iar --output my_report.html --title "MyIntegration Diff"

# Generate the report without opening it in a browser
python oic_iar_diff.py v1.iar v2.iar --no-browser
```

### Arguments

| Argument | Description |
|---|---|
| `v1` | Path to the baseline IAR file or extracted folder |
| `v2` | Path to the new version IAR file or extracted folder |
| `--output`, `-o` | Output HTML file path (default: `iar_diff_report.html`) |
| `--title` | Custom title displayed in the report header |
| `--no-browser` | Suppress automatic browser launch after report generation |

---

## Output

The tool prints a console summary of changes per category and writes a single HTML file containing the full diff report. If `--no-browser` is not set, the report is opened automatically in the default browser.

Example console output:

```
[OIC IAR Diff]  Loading v1: MyIntegration_1.0.iar
  → 42 files loaded
[OIC IAR Diff]  Loading v2: MyIntegration_1.1.iar
  → 45 files loaded

[OIC IAR Diff]  Comparing 'MyIntegration v1.0' vs 'MyIntegration v1.1' ...

[OIC IAR Diff]  Summary:
  📋 Project Metadata                             ~2
  🔌 Connections (appinstances)                   =3
  🔄 XSLT Mapper Transformations                  ~1, =4
  ⚙️  JCA Adapter Configurations                  +1, =2

  Total changes: 4

[OIC IAR Diff]  Report written to: C:\...\iar_diff_report.html
```

---

## File Structure

| File | Purpose |
|---|---|
| `oic_iar_diff.py` | Core diff logic — IAR loading, artifact comparison, CLI entry point |
| `iar_report_assets.py` | HTML report rendering — CSS, JavaScript, and the `HTMLReporter` class |


---

## Customisation

To adjust the report's visual style or client-side behaviour without touching the diff logic, edit `iar_report_assets.py`:

- **CSS** — Modify the `CSS` string to change colors, fonts, or layout
- **JS** — Modify the `JS` string to change interactive behaviour
- **`HTMLReporter`** — Override `_render_category()` or `_item_html()` to change report structure
