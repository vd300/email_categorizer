from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import text

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs = {"connect_args": connect_args, "pool_pre_ping": True}
if settings.database_url == "sqlite:///:memory:":
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    from app.models.email import Email, GmailCredential, GmailOAuthState  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_email_profiles(engine)


def _migrate_sqlite_email_profiles(db_engine: Engine) -> None:
    if db_engine.dialect.name != "sqlite":
        return

    with db_engine.begin() as connection:
        table_exists = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'emails'")
        ).scalar_one_or_none()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info('emails')").fetchall()
        }
        has_profile = "profile" in columns
        has_global_provider_unique = _has_global_provider_message_unique_index(connection)
        if has_profile and not has_global_provider_unique:
            return

        connection.exec_driver_sql("DROP TABLE IF EXISTS emails_migration")
        connection.exec_driver_sql(
            """
            CREATE TABLE emails_migration (
                id INTEGER NOT NULL,
                profile VARCHAR(120) NOT NULL DEFAULT 'default',
                provider_message_id VARCHAR(255),
                thread_id VARCHAR(255),
                sender VARCHAR(320) NOT NULL,
                recipients TEXT,
                subject VARCHAR(500) NOT NULL,
                body TEXT NOT NULL,
                received_at DATETIME,
                category VARCHAR(80) NOT NULL,
                priority_score FLOAT NOT NULL,
                urgent BOOLEAN NOT NULL,
                needs_reply BOOLEAN NOT NULL,
                summary TEXT NOT NULL,
                action_items TEXT NOT NULL,
                labels TEXT NOT NULL,
                draft_reply TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_emails_profile_provider_message
                    UNIQUE (profile, provider_message_id)
            )
            """
        )
        profile_expression = "profile" if has_profile else "'default'"
        connection.exec_driver_sql(
            f"""
            INSERT INTO emails_migration (
                id, profile, provider_message_id, thread_id, sender, recipients, subject, body,
                received_at, category, priority_score, urgent, needs_reply, summary,
                action_items, labels, draft_reply, created_at, updated_at
            )
            SELECT
                id, {profile_expression}, provider_message_id, thread_id, sender, recipients,
                subject, body, received_at, category, priority_score, urgent, needs_reply,
                summary, action_items, labels, draft_reply, created_at, updated_at
            FROM emails
            """
        )
        connection.exec_driver_sql("DROP TABLE emails")
        connection.exec_driver_sql("ALTER TABLE emails_migration RENAME TO emails")
        connection.exec_driver_sql("CREATE INDEX ix_emails_id ON emails (id)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_profile ON emails (profile)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_thread_id ON emails (thread_id)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_sender ON emails (sender)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_subject ON emails (subject)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_category ON emails (category)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_urgent ON emails (urgent)")
        connection.exec_driver_sql("CREATE INDEX ix_emails_needs_reply ON emails (needs_reply)")
        connection.exec_driver_sql(
            "CREATE INDEX ix_emails_profile_priority_received "
            "ON emails (profile, priority_score, received_at)"
        )


def _has_global_provider_message_unique_index(connection: Connection) -> bool:
    indexes = connection.exec_driver_sql("PRAGMA index_list('emails')").fetchall()
    for index in indexes:
        index_name = index[1]
        is_unique = bool(index[2])
        if not is_unique:
            continue
        indexed_columns = [
            row[2]
            for row in connection.exec_driver_sql(f"PRAGMA index_info('{index_name}')").fetchall()
        ]
        if indexed_columns == ["provider_message_id"]:
            return True
    return False
