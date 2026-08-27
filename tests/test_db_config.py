from db.config import migration_database_url


def test_migration_url_prefers_explicit_unpooled_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@pooled.example/db")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://user:pass@direct.example/db")

    assert migration_database_url() == "postgresql://user:pass@direct.example/db"


def test_migration_url_removes_only_neon_pooler_hostname_suffix(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:p%40ss@ep-example-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
    )

    assert migration_database_url() == (
        "postgresql://user:p%40ss@ep-example.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )


def test_migration_url_keeps_an_existing_direct_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    direct = "postgresql://user:pass@ep-example.us-east-2.aws.neon.tech/neondb"
    monkeypatch.setenv("DATABASE_URL", direct)

    assert migration_database_url() == direct
