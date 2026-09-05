from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    app_env:str='local'; secret_key:str='change-me'
    database_url:str='postgresql+psycopg://quantlab:quantlab@db:5432/quantlab'; redis_url:str='redis://redis:6379/0'
    data_mode:str='synthetic'; synthetic_seed:int=42; synthetic_symbols:int=120; synthetic_years:int=6
    alpaca_api_key:str=''; alpaca_secret_key:str=''; alpaca_paper_base_url:str='https://paper-api.alpaca.markets'; alpaca_data_base_url:str='https://data.alpaca.markets'
    alpaca_feed:str='iex'; real_history_start:str='2016-01-01'; real_history_years:int=5
    real_universe_size:int=120; real_universe_prefilter_size:int=250
    real_universe_min_price:float=10.0; real_universe_min_history_sessions:int=1000
    real_universe_min_median_dollar_volume:float=50000000.0; real_universe_max_volatility:float=0.65
    real_universe_min_sec_core_metrics:int=3
    sec_user_agent:str='QuantLab local research contact@example.com'
    trading_env:str='PAPER'; paper_auto_enabled:bool=False; allow_alpaca_paper_orders:bool=False
    paper_auto_weekday:int=0; paper_auto_hour_et:int=9; paper_auto_minute_et:int=35; paper_auto_top_n:int=20
    daily_pipeline_enabled:bool=True; daily_pipeline_hour_et:int=18; daily_pipeline_minute_et:int=15; daily_sec_refresh_weekday:int=5
    auto_bootstrap_enabled:bool=True
    model_config=SettingsConfigDict(env_file='.env',extra='ignore')
settings=Settings()
