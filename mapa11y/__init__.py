"""MapA11y Audit - map-aware accessibility auditing of public government web maps.

Pipeline:
  1. sample     - Census sampling frame -> stratified random sample of governments
  2. discover   - find each government's ArcGIS Online organization, then its most-viewed public map apps
  3. audit      - automated WCAG 2.1 A/AA checks (axe-core) + map-specific keyboard/name/alternative checks
  4. summarize  - flatten results, summary tables, manual-validation sample
"""
__version__ = "0.4.7"
