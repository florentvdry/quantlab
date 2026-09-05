from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cagr: Mapped[float] = mapped_column(Float)
    sharpe: Mapped[float] = mapped_column(Float)
    max_drawdown: Mapped[float] = mapped_column(Float)
    volatility: Mapped[float] = mapped_column(Float)
    turnover: Mapped[float] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text)

class BrokerConnection(Base):
    __tablename__ = "broker_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), default="simulated")
    environment: Mapped[str] = mapped_column(String(20), default="PAPER")
    connected: Mapped[bool] = mapped_column(Boolean, default=True)
    equity: Mapped[float] = mapped_column(Float, default=100000.0)
    cash: Mapped[float] = mapped_column(Float, default=100000.0)
    buying_power: Mapped[float] = mapped_column(Float, default=200000.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True)
    side: Mapped[str] = mapped_column(String(10))
    notional: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text)

class RebalanceRun(Base):
    __tablename__ = "rebalance_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    rebalance_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(120), default="META US v1")
    status: Mapped[str] = mapped_column(String(30), default="PREVIEW")
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class BrokerOrder(Base):
    __tablename__ = "broker_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    rebalance_key: Mapped[str] = mapped_column(String(120), index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(10))
    notional: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    model_type: Mapped[str] = mapped_column(String(40), default="weighted")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), default="SWEEP")
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), default="PAPER", index=True)
    strategy_name: Mapped[str] = mapped_column(String(120), default="META US v1")
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    buying_power: Mapped[float] = mapped_column(Float, default=0.0)
    long_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    short_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    gross_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    net_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    position_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class SystemState(Base):
    __tablename__ = "system_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TradeFill(Base):
    __tablename__ = "trade_fills"
    id: Mapped[int] = mapped_column(primary_key=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    notional: Mapped[float] = mapped_column(Float, default=0.0)
    event: Mapped[str] = mapped_column(String(30), default="fill")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
