"""Export a local laboratory audit database without overwriting a destination."""
import argparse
from pathlib import Path
from .storage import AuditError, AuditStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.audit.is_file():
            raise AuditError("Audit database does not exist")
        # Exclusively claim the output name; even a concurrent export cannot
        # overwrite an existing result. A failed export leaves a visible file.
        with args.output.open("x"):
            pass
        AuditStore(args.audit).export(args.output)
    except (AuditError, OSError, ValueError) as exc:
        parser.exit(1, f"Audit export rejected: {exc}\n")
    print(f"Audit exported to {args.output}")


if __name__ == "__main__":
    main()
