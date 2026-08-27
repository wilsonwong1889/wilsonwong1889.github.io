from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

# pool_pre_ping: managed Postgres closes idle connections server-side, so the
# pool can hand out a dead handle after a quiet period — the first real visitor
# then eats an OperationalError. pre_ping costs one cheap round-trip and
# transparently reconnects instead. pool_recycle stays under typical idle
# timeouts so connections are retired before the server drops them.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass


@event.listens_for(Base.metadata, "before_create")
def enable_postgres_extensions(_metadata, connection, **_kwargs):
    if connection.dialect.name == "postgresql":
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
