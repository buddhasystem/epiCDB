#!/usr/bin/env python3
"""
cdb — command-line interface to the Component Database.

Run from the project root (next to manage.py):

    bin/cdb <command> [args]

Add bin/ to PATH to invoke as just "cdb" from anywhere.

Commands
--------
  institutions                  List all institutions
  location-tree  <ABBR>         Location hierarchy for an institution
  systems                       List technical systems with counts
  search         <QUERY>        Cross-domain keyword search
  component      <NAME>         Component summary (JSON)
  inventory      <QR_ID>        Instance detail (JSON)
  where          <QR_ID>        Where is this item right now?
  bom            <DESIGN_NAME>  Bill of Materials (JSON)

Options
-------
  --settings  Django settings module  [default: cdb_project.settings]
  --root      Project root directory  [default: parent of bin/]
  --json      Force JSON output for all commands
"""

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _setup(args):
    # Default root: parent of the bin/ directory this script lives in
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)

    import django.conf
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)
    if not django.conf.settings.configured:
        import django
        django.setup()

    from cdb_client import CDBClient
    return CDBClient()


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _json(obj):
    print(json.dumps(obj, indent=2, default=str))


def _table(rows, headers):
    """Print an aligned plain-text table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_institutions(client, args):
    insts = client.locations.all_institutions()
    if args.json:
        _json([{"id": i.pk, "name": i.name, "abbreviation": i.abbreviation,
                "city": i.city, "country": i.country, "url": i.url}
               for i in insts])
    else:
        _table(
            [(i.abbreviation, i.name, i.city, i.country) for i in insts],
            ["Abbr", "Name", "City", "Country"],
        )


def cmd_location_tree(client, args):
    tree = client.locations.location_tree(args.abbr)
    if args.json:
        _json(tree)
    else:
        def _print(nodes, indent=0):
            for node in nodes:
                print("  " * indent + f"[{node['type']}] {node['name']}")
                _print(node["children"], indent + 1)
        _print(tree)


def cmd_systems(client, args):
    rows = client.systems.instance_counts()
    if args.json:
        _json(rows)
    else:
        _table(
            [(r["name"], r["components"], r["instances"]) for r in rows],
            ["Technical System", "Components", "Instances"],
        )


def cmd_search(client, args):
    query = " ".join(args.query)
    results = client.search_all(query)
    if args.json:
        _json(results)
    else:
        for domain, items in results.items():
            print(f"\n-- {domain} --")
            if not items:
                print("  (none)")
            for item in items:
                parts = "  " + "  |  ".join(f"{k}: {v}" for k, v in item.items() if v)
                print(parts)


def cmd_component(client, args):
    name = " ".join(args.name)
    try:
        data = client.catalog.summary(name)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    _json(data)


def cmd_inventory(client, args):
    try:
        data = client.inventory.detail(args.qr_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    _json(data)


def cmd_where(client, args):
    try:
        data = client.where_is(args.qr_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        _json(data)
    else:
        print(f"QR ID    : {data['qr_id']}")
        print(f"Component: {data['component']}")
        print(f"System   : {data['technical_system'] or '--'}")
        print(f"Location : {data['location'] or '--'}")
        site = data.get("institution") or "--"
        geo  = f"  ({data['city']}, {data['country']})" if data.get("city") else ""
        print(f"Site     : {site}{geo}")


def cmd_bom(client, args):
    name = " ".join(args.name)
    try:
        data = client.designs.bom(name)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        _json(data)
    else:
        def _print(rows, indent=0):
            for row in rows:
                prefix = "  " * indent
                tag = f"[{row['type']}]"
                ref = row.get("ref") or ""
                qty = row.get("qty", 1)
                print(f"{prefix}{tag} {row['element']}  x{qty}  -> {ref}")
                _print(row.get("children", []), indent + 1)
        _print(data)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="cdb",
        description="Command-line interface to the Component Database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--settings", default="cdb_project.settings",
                   metavar="MODULE",
                   help="Django settings module (default: cdb_project.settings)")
    p.add_argument("--root", default=None,
                   metavar="DIR",
                   help="Project root directory (default: parent of bin/)")
    p.add_argument("--json", action="store_true",
                   help="Force JSON output")

    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    sub.add_parser("institutions",
                   help="List all institutions")

    sp = sub.add_parser("location-tree",
                        help="Location hierarchy for an institution")
    sp.add_argument("abbr", metavar="ABBR",
                    help="Institution abbreviation, e.g. BNL")

    sub.add_parser("systems",
                   help="List technical systems with component/instance counts")

    sp = sub.add_parser("search",
                        help="Cross-domain keyword search")
    sp.add_argument("query", nargs="+", metavar="WORD")

    sp = sub.add_parser("component",
                        help="Show component summary (JSON)")
    sp.add_argument("name", nargs="+", metavar="NAME")

    sp = sub.add_parser("inventory",
                        help="Show instance detail (JSON)")
    sp.add_argument("qr_id", metavar="QR_ID")

    sp = sub.add_parser("where",
                        help="Where is a QR-coded item right now?")
    sp.add_argument("qr_id", metavar="QR_ID")

    sp = sub.add_parser("bom",
                        help="Print Bill of Materials for a design")
    sp.add_argument("name", nargs="+", metavar="DESIGN_NAME")

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "institutions":  cmd_institutions,
    "location-tree": cmd_location_tree,
    "systems":       cmd_systems,
    "search":        cmd_search,
    "component":     cmd_component,
    "inventory":     cmd_inventory,
    "where":         cmd_where,
    "bom":           cmd_bom,
}

if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()
    client = _setup(args)
    COMMANDS[args.command](client, args)
