"""テストから**実ネットワークへ出ない**ことを機械的に保証する。

★中央側で、取得関数の差し替えを忘れたテストが本当に netkeiba を叩き、
  テストが終わらなくなった前例がある。外に出るテストは遅いだけでなく、
  相手の都合で落ちるし、相手に迷惑をかける。
"""

from __future__ import annotations

import socket
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, request):
    if request.node.get_closest_marker("network"):
        return

    def _blocked(*a, **k):
        raise RuntimeError("テストから外部へ接続しようとしました。取得関数を差し替えてください")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def pytest_configure(config):
    config.addinivalue_line("markers", "network: 実ネットワークを使う(既定では塞がれる)")
