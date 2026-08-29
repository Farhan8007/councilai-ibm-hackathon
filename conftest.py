"""
Root conftest.py — exclude source directories from pytest collection so that
agent class names (e.g. TestingAgent) do not trigger PytestCollectionWarning.
"""

collect_ignore_glob = ["agents/*.py", "backend/*.py"]
