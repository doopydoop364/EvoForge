"""Database migrations run transactionally through Database initialization."""

from .database import SCHEMA_VERSION, Database


def migrate_database(root):
    database = Database(root)
    return {"path": str(database.path), "schema_version": SCHEMA_VERSION}
