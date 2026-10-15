"""設定。環境変数(.env 含む) > 既定値。中央と同じ DB を使い、テーブルだけ分ける。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_schema() -> Path:
    """★スキーマの正本は hro-db。こちらで二重管理しない。"""
    return _repo_root() / "hro-db" / "schema" / "36_nar_odds.sql"


@dataclass
class PostgresConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    dbname: str = "hro"
    user: str = "postgres"
    password: str = ""
    sslmode: str = ""


@dataclass
class CollectConfig:
    # 発走この分前から収集対象にする
    window_min: int = 25
    # 発走後この分までは見る(確定オッズの取得。★判断には使わない)
    grace_min: int = 3
    # 1周の間隔(秒)。配信は中央値31秒なので、これで十分細かい
    interval_sec: float = 8.0
    # SPAT4 で買う前提か(南関東の締切が1分前になる)
    spat4: bool = False
    # 保存済み netkeiba セッション
    state_path: str = ""


@dataclass
class Config:
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    collect: CollectConfig = field(default_factory=CollectConfig)
    schema_path: Path = field(default_factory=_default_schema)
    log_level: str = "INFO"


def _b(v: str | None, default: bool) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    load_dotenv()
    e = os.environ.get
    pg = PostgresConfig(
        host=e("POSTGRES_HOST", "127.0.0.1"),
        port=int(e("POSTGRES_PORT", "5432")),
        dbname=e("POSTGRES_DATABASE", "hro"),
        user=e("POSTGRES_USER", "postgres"),
        password=e("POSTGRES_PASSWORD", ""),
        sslmode=e("POSTGRES_SSLMODE", ""),
    )
    col = CollectConfig(
        window_min=int(e("NAR_WINDOW_MIN", "25")),
        grace_min=int(e("NAR_GRACE_MIN", "3")),
        interval_sec=float(e("NAR_INTERVAL_SEC", "8")),
        spat4=_b(e("NAR_SPAT4"), False),
        state_path=e("NETKEIBA_STATE", ""),
    )
    sp = e("NAR_SCHEMA_PATH")
    return Config(postgres=pg, collect=col,
                  schema_path=Path(sp) if sp else _default_schema(),
                  log_level=e("LOG_LEVEL", "INFO"))
