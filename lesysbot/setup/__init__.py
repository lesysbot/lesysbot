"""`lesysbot setup` — the interactive install/reconfigure wizard.

One cross-platform implementation (Rich panels, arrow-key navigation) shared by
every OS. ``scripts/install.sh`` only bootstraps — Python check, pip
install — then hand off here; running ``lesysbot setup`` directly reconfigures an
existing install at any time.

Module layout: ``ui.py`` widgets, ``wizard.py`` the step chain and state,
``apply.py`` what Apply writes (config, tools, service), ``cli.py`` the
argparse wiring and top-level flow.
"""
