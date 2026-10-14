"""Database migrations run transactionally through Database initialization."""
from .database import Database, SCHEMA_VERSION


def migrate_database(root):
    database = Database(root)
    return {'path': str(database.path), 'schema_version': SCHEMA_VERSION}
