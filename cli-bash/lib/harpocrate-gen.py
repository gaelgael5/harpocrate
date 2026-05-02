#!/usr/bin/env python3
"""Shim d'entrée pour harpocrate-gen depuis le répertoire cli-bash/lib/.

Ce fichier permet d'utiliser harpocrate-gen sans que le package soit installé
via pip, en ajoutant le répertoire sdk-python/ au sys.path.

Usage depuis bash (quand le SDK n'est pas installé) :
    python3 cli-bash/lib/harpocrate-gen.py <command> [args...]

Usage recommandé (après pip install) :
    harpocrate-gen <command> [args...]
"""
from __future__ import annotations

import os
import sys

# Détecte l'emplacement du SDK par rapport à ce fichier
_lib_dir = os.path.dirname(os.path.abspath(__file__))
_cli_bash_dir = os.path.dirname(_lib_dir)
_repo_root = os.path.dirname(_cli_bash_dir)
_sdk_dir = os.path.join(_repo_root, "sdk-python")

# Ajoute sdk-python/ au path si harpocrate n'est pas déjà installé
try:
    import harpocrate  # noqa: F401
except ImportError:
    if os.path.isdir(_sdk_dir):
        sys.path.insert(0, _sdk_dir)
        try:
            import harpocrate  # noqa: F401
        except ImportError as exc:
            print(
                f"ERROR: Could not import harpocrate. "
                f"Install with: pip install harpocrate\n"
                f"Details: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            "ERROR: harpocrate not found. Install with: pip install harpocrate",
            file=sys.stderr,
        )
        sys.exit(1)

from harpocrate.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
