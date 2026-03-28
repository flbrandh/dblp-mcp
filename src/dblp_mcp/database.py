"""SQLite connection and schema helpers for the DBLP MCP server."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4


def connect(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            records_processed INTEGER NOT NULL DEFAULT 0,
            source_size_bytes INTEGER,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dblp_key TEXT NOT NULL UNIQUE,
            record_type TEXT NOT NULL,
            title TEXT NOT NULL,
            title_norm TEXT NOT NULL,
            year INTEGER,
            pages TEXT,
            volume TEXT,
            number TEXT,
            chapter TEXT,
            crossref TEXT,
            month TEXT,
            address TEXT,
            note TEXT,
            source_mdate TEXT
        );

        CREATE TABLE IF NOT EXISTS contributors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            UNIQUE(name_norm, name)
        );

        CREATE TABLE IF NOT EXISTS publication_contributors (
            publication_id INTEGER NOT NULL,
            contributor_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (publication_id, role, position),
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE,
            FOREIGN KEY (contributor_id) REFERENCES contributors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS venues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            venue_type TEXT NOT NULL,
            UNIQUE(name_norm, venue_type)
        );

        CREATE TABLE IF NOT EXISTS publication_venues (
            publication_id INTEGER NOT NULL,
            venue_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (publication_id, venue_id, relation_type, position),
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE,
            FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS publication_identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(publication_id, kind, value),
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS publication_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            field_value TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS publication_abstracts (
            publication_id INTEGER PRIMARY KEY,
            abstract_text TEXT NOT NULL,
            abstract_norm TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS abstract_fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER,
            dblp_key TEXT,
            provider TEXT NOT NULL,
            attempted_url TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_publications_year ON publications(year);
        CREATE INDEX IF NOT EXISTS idx_publications_type_year ON publications(record_type, year);
        CREATE INDEX IF NOT EXISTS idx_publications_title_norm ON publications(title_norm);
        CREATE INDEX IF NOT EXISTS idx_contributors_name_norm ON contributors(name_norm);
        CREATE INDEX IF NOT EXISTS idx_venues_name_norm ON venues(name_norm);
        CREATE INDEX IF NOT EXISTS idx_pub_contributor_lookup ON publication_contributors(contributor_id, role, publication_id);
        CREATE INDEX IF NOT EXISTS idx_pub_venue_lookup ON publication_venues(venue_id, relation_type, publication_id);
        CREATE INDEX IF NOT EXISTS idx_pub_identifier_lookup ON publication_identifiers(kind, value);

        CREATE TABLE IF NOT EXISTS publication_fulltexts (
            publication_id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            pdf_url TEXT NOT NULL,
            local_pdf_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            page_count INTEGER NOT NULL,
            full_text TEXT NOT NULL,
            full_text_norm TEXT NOT NULL,
            image_status TEXT NOT NULL,
            page_image_paths_json TEXT NOT NULL DEFAULT '[]',
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fulltext_fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER,
            dblp_key TEXT,
            provider TEXT NOT NULL,
            attempted_url TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_abstract_fetch_logs_publication ON abstract_fetch_logs(publication_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_abstract_fetch_logs_status ON abstract_fetch_logs(status, created_at);

        INSERT INTO metadata(key, value)
        VALUES ('schema_version', '{SCHEMA_VERSION}')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """)

    connection.execute("DROP TABLE IF EXISTS publication_search")
    connection.execute("""
        CREATE VIRTUAL TABLE publication_search USING fts5(
            dblp_key UNINDEXED,
            title,
            contributors,
            venues,
            content=''
        )
        """)


def ensure_abstract_schema(connection: sqlite3.Connection) -> None:
    """Create abstract-related tables on existing databases if needed.

    This helper is additive: it extends previously built databases with the
    abstract cache and abstract log tables without rebuilding the full FTS index.
    """
    connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS publication_abstracts (
            publication_id INTEGER PRIMARY KEY,
            abstract_text TEXT NOT NULL,
            abstract_norm TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS abstract_fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER,
            dblp_key TEXT,
            provider TEXT NOT NULL,
            attempted_url TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_abstract_fetch_logs_publication ON abstract_fetch_logs(publication_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_abstract_fetch_logs_status ON abstract_fetch_logs(status, created_at);

        INSERT INTO metadata(key, value)
        VALUES ('schema_version', '{SCHEMA_VERSION}')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """)


def rebuild_search_index(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM publication_search")
    connection.execute("""
        INSERT INTO publication_search(rowid, dblp_key, title, contributors, venues)
        SELECT
            publications.id,
            publications.dblp_key,
            publications.title,
            COALESCE(
                (
                    SELECT group_concat(contributors.name, ' ')
                    FROM publication_contributors
                    JOIN contributors ON contributors.id = publication_contributors.contributor_id
                    WHERE publication_contributors.publication_id = publications.id
                    ORDER BY publication_contributors.position
                ),
                ''
            ),
            COALESCE(
                (
                    SELECT group_concat(venues.name, ' ')
                    FROM publication_venues
                    JOIN venues ON venues.id = publication_venues.venue_id
                    WHERE publication_venues.publication_id = publications.id
                    ORDER BY publication_venues.position
                ),
                ''
            )
        FROM publications
        """)


def ensure_fulltext_schema(connection: sqlite3.Connection) -> None:
    """Create fulltext-related tables on existing databases if needed."""
    connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS publication_fulltexts (
            publication_id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            pdf_url TEXT NOT NULL,
            local_pdf_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            page_count INTEGER NOT NULL,
            full_text TEXT NOT NULL,
            full_text_norm TEXT NOT NULL,
            image_status TEXT NOT NULL,
            page_image_paths_json TEXT NOT NULL DEFAULT '[]',
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fulltext_fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER,
            dblp_key TEXT,
            provider TEXT NOT NULL,
            attempted_url TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fulltext_fetch_logs_publication ON fulltext_fetch_logs(publication_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_fulltext_fetch_logs_status ON fulltext_fetch_logs(status, created_at);

        INSERT INTO metadata(key, value)
        VALUES ('schema_version', '{SCHEMA_VERSION}')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """)
