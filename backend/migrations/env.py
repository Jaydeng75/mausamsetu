"""Run migrations only after the database accepts actual TCP connections."""
import os,time
from alembic import context
from sqlalchemy import create_engine,pool
from sqlalchemy.exc import OperationalError
from mausam.storage import Base

config=context.config
url=os.getenv('DATABASE_URL') or config.get_main_option('sqlalchemy.url')
if context.is_offline_mode():
    context.configure(url=url,target_metadata=Base.metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
else:
    engine=create_engine(url,poolclass=pool.NullPool)
    for attempt in range(15):
        try:
            connection=engine.connect()
            break
        except OperationalError:
            if attempt==14:raise
            time.sleep(2)
    with connection:
        context.configure(connection=connection,target_metadata=Base.metadata)
        with context.begin_transaction():context.run_migrations()
