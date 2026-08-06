"""Rendering and provisioning for installed dashboard packages.

A dashboard *package* is source the user owns (``~/.lesysbot/dashboard/installed/``);
the rendered JSON Grafana reads is derived output, rewritten on every render.
Keeping those separate is what lets an edit survive an update — the thing the
pre-refactor stack could not do, since it regenerated its single dashboard on
every start and mounted it read-only.
"""
