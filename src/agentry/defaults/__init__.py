"""Bundled default configurations and role rule files.

The ``standard/`` subpackage contains the canonical 6-role config + role rule
files that Agentry uses when a target repo doesn't override them. Files here
are loaded via ``importlib.resources`` so they survive packaging into a wheel.
"""
