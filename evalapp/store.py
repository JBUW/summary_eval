"""The results store: one SQLite file, exactly 8 tables (docs/store-schema.md).

Single shared open path: an absent file or a file with zero tables is
bootstrapped (directory, file, all 8 tables); an existing file with at
least one table must match the documented schema exactly, else opening is
a pre-effect failure with a hint to move or delete the file. There is
never migration. ``Store.open_readonly`` never bootstraps: an absent file
yields ``None`` and a zero-table file is a valid empty store; one or more
tables get the same exact schema check. Every row is addressed by its
identity sha256; inserting
an existing identity upserts under the stamp rule — updated_at moves only
when a non-identity value differs from what is stored, and a pure
re-insert leaves the row untouched.
"""
import os
import sqlite3
import time

from .errors import RuntimeFailure, SpecError
from .identities import (
    canonical_json,
    generation_id,
    judge_evaluation_id,
    judge_id,
    metric_evaluation_id,
    model_id,
    summary_id,
    template_id,
    transcript_id,
)

TABLES = (
    "transcripts",
    "reference_summaries",
    "models",
    "prompt_templates",
    "generations",
    "judges",
    "judge_evaluations",
    "metric_evaluations",
)

_MISMATCH = (
    "store at {path} does not match the expected schema "
    "(move or delete the file to start a fresh store)"
)

_DDL = {
    "transcripts": """
        CREATE TABLE transcripts (
            transcript_sha256 TEXT PRIMARY KEY,
            transcript_text TEXT NOT NULL,
            dataset_name TEXT NOT NULL,
            entry_id TEXT,
            entry_index INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "reference_summaries": """
        CREATE TABLE reference_summaries (
            summary_sha256 TEXT PRIMARY KEY,
            summary_text TEXT NOT NULL,
            transcript_sha256 TEXT NOT NULL REFERENCES transcripts(transcript_sha256),
            dataset_name TEXT NOT NULL,
            entry_id TEXT,
            entry_index INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "models": """
        CREATE TABLE models (
            model_sha256 TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model_path TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "prompt_templates": """
        CREATE TABLE prompt_templates (
            template_sha256 TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            system_content TEXT NOT NULL,
            user_prefix TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "judges": """
        CREATE TABLE judges (
            judge_sha256 TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            model_name TEXT NOT NULL,
            gen_params TEXT NOT NULL,
            system_content TEXT NOT NULL,
            user_template TEXT NOT NULL,
            requires_reference INTEGER NOT NULL,
            api_key_env TEXT,
            updated_at TEXT NOT NULL
        )
    """,
    "generations": """
        CREATE TABLE generations (
            generation_sha256 TEXT PRIMARY KEY,
            generation_text TEXT NOT NULL,
            transcript_sha256 TEXT NOT NULL REFERENCES transcripts(transcript_sha256),
            model_sha256 TEXT NOT NULL REFERENCES models(model_sha256),
            model_args TEXT NOT NULL,
            template_sha256 TEXT NOT NULL REFERENCES prompt_templates(template_sha256),
            gen_params TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "judge_evaluations": """
        CREATE TABLE judge_evaluations (
            judge_evaluation_sha256 TEXT PRIMARY KEY,
            judge_sha256 TEXT NOT NULL REFERENCES judges(judge_sha256),
            generation_sha256 TEXT NOT NULL REFERENCES generations(generation_sha256),
            reference_summary_sha256 TEXT REFERENCES reference_summaries(summary_sha256),
            factual_correctness REAL,
            completeness REAL,
            conciseness REAL,
            updated_at TEXT NOT NULL
        )
    """,
    "metric_evaluations": """
        CREATE TABLE metric_evaluations (
            metric_evaluation_sha256 TEXT PRIMARY KEY,
            metric_name TEXT NOT NULL,
            generation_sha256 TEXT NOT NULL REFERENCES generations(generation_sha256),
            reference_summary_sha256 TEXT REFERENCES reference_summaries(summary_sha256),
            value REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
}

# (name, declared type, notnull, pk) per column, in table order.
_EXPECTED_COLUMNS = {
    "transcripts": (
        ("transcript_sha256", "TEXT", 0, 1),
        ("transcript_text", "TEXT", 1, 0),
        ("dataset_name", "TEXT", 1, 0),
        ("entry_id", "TEXT", 0, 0),
        ("entry_index", "INTEGER", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "reference_summaries": (
        ("summary_sha256", "TEXT", 0, 1),
        ("summary_text", "TEXT", 1, 0),
        ("transcript_sha256", "TEXT", 1, 0),
        ("dataset_name", "TEXT", 1, 0),
        ("entry_id", "TEXT", 0, 0),
        ("entry_index", "INTEGER", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "models": (
        ("model_sha256", "TEXT", 0, 1),
        ("name", "TEXT", 1, 0),
        ("model_path", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "prompt_templates": (
        ("template_sha256", "TEXT", 0, 1),
        ("name", "TEXT", 1, 0),
        ("system_content", "TEXT", 1, 0),
        ("user_prefix", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "judges": (
        ("judge_sha256", "TEXT", 0, 1),
        ("name", "TEXT", 1, 0),
        ("endpoint", "TEXT", 1, 0),
        ("model_name", "TEXT", 1, 0),
        ("gen_params", "TEXT", 1, 0),
        ("system_content", "TEXT", 1, 0),
        ("user_template", "TEXT", 1, 0),
        ("requires_reference", "INTEGER", 1, 0),
        ("api_key_env", "TEXT", 0, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "generations": (
        ("generation_sha256", "TEXT", 0, 1),
        ("generation_text", "TEXT", 1, 0),
        ("transcript_sha256", "TEXT", 1, 0),
        ("model_sha256", "TEXT", 1, 0),
        ("model_args", "TEXT", 1, 0),
        ("template_sha256", "TEXT", 1, 0),
        ("gen_params", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "judge_evaluations": (
        ("judge_evaluation_sha256", "TEXT", 0, 1),
        ("judge_sha256", "TEXT", 1, 0),
        ("generation_sha256", "TEXT", 1, 0),
        ("reference_summary_sha256", "TEXT", 0, 0),
        ("factual_correctness", "REAL", 0, 0),
        ("completeness", "REAL", 0, 0),
        ("conciseness", "REAL", 0, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "metric_evaluations": (
        ("metric_evaluation_sha256", "TEXT", 0, 1),
        ("metric_name", "TEXT", 1, 0),
        ("generation_sha256", "TEXT", 1, 0),
        ("reference_summary_sha256", "TEXT", 0, 0),
        ("value", "REAL", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
}

# (from column, to table) per declared foreign key.
_EXPECTED_FOREIGN_KEYS = {
    "transcripts": frozenset(),
    "reference_summaries": frozenset({("transcript_sha256", "transcripts")}),
    "models": frozenset(),
    "prompt_templates": frozenset(),
    "judges": frozenset(),
    "generations": frozenset(
        {
            ("transcript_sha256", "transcripts"),
            ("model_sha256", "models"),
            ("template_sha256", "prompt_templates"),
        }
    ),
    "judge_evaluations": frozenset(
        {
            ("judge_sha256", "judges"),
            ("generation_sha256", "generations"),
            ("reference_summary_sha256", "reference_summaries"),
        }
    ),
    "metric_evaluations": frozenset(
        {
            ("generation_sha256", "generations"),
            ("reference_summary_sha256", "reference_summaries"),
        }
    ),
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, path, readonly=False):
        self.path = path
        self.created = False
        self.readonly = readonly
        if not readonly and not os.path.exists(path) and os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._db = self._connect(readonly)
        try:
            tables = self._table_names()
            if not tables and not readonly:
                with self._db:
                    for table in TABLES:
                        self._db.execute(_DDL[table])
                self.created = True
            elif tables:
                self._verify_schema(tables)
        except SpecError:
            self._db.close()
            raise
        if not readonly:
            self._db.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open_readonly(cls, path):
        """Read-only open: None when the file is absent (never bootstraps);
        a zero-table file is a valid empty store; one or more tables get
        the same exact schema check."""
        if not os.path.exists(path):
            return None
        return cls(path, readonly=True)

    def _connect(self, readonly):
        if readonly:
            target, kwargs = f"file:{self.path}?mode=ro", {"uri": True}
        else:
            target, kwargs = self.path, {}
        try:
            return sqlite3.connect(target, **kwargs)
        except sqlite3.Error as exc:
            raise SpecError(f"cannot open store at {self.path}: {exc}") from exc

    def _table_names(self):
        try:
            return {
                row[0]
                for row in self._db.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        except sqlite3.DatabaseError as exc:
            self._db.close()
            raise SpecError(_MISMATCH.format(path=self.path)) from exc

    def _verify_schema(self, tables):
        if tables != set(TABLES):
            raise SpecError(_MISMATCH.format(path=self.path))
        for table in TABLES:
            if self._columns(table) != _EXPECTED_COLUMNS[table]:
                raise SpecError(_MISMATCH.format(path=self.path))
            if self._foreign_keys(table) != _EXPECTED_FOREIGN_KEYS[table]:
                raise SpecError(_MISMATCH.format(path=self.path))

    @staticmethod
    def _columns_of(db, table):
        return tuple(
            (row[1], row[2], row[3], row[5])
            for row in db.execute(f"PRAGMA table_info({table})")
        )

    @staticmethod
    def _foreign_keys_of(db, table):
        return frozenset(
            (row[3], row[2]) for row in db.execute(f"PRAGMA foreign_key_list({table})")
        )

    def _columns(self, table):
        return self._columns_of(self._db, table)

    def _foreign_keys(self, table):
        return self._foreign_keys_of(self._db, table)

    def _execute(self, sql, params):
        try:
            with self._db:
                return self._db.execute(sql, params)
        except sqlite3.Error as exc:
            raise RuntimeFailure(f"store operation failed on {self.path}: {exc}") from exc

    def _upsert(self, table, pk_column, pk_value, columns, values, stamps):
        all_columns = [pk_column, *columns, "updated_at"]
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns)
        stamp_check = " OR ".join(
            f"{column} IS NOT excluded.{column}" for column in stamps
        )
        sql = (
            f"INSERT INTO {table} ({', '.join(all_columns)}) "
            f"VALUES ({', '.join('?' * len(all_columns))}) "
            f"ON CONFLICT ({pk_column}) DO UPDATE SET {updates}, "
            f"updated_at = CASE WHEN {stamp_check} "
            f"THEN excluded.updated_at ELSE updated_at END"
        )
        self._execute(sql, (pk_value, *values, _now()))
        return pk_value

    def upsert_transcript(self, text, dataset_name, entry_id, entry_index):
        sha = transcript_id(text)
        columns = ("transcript_text", "dataset_name", "entry_id", "entry_index")
        self._upsert(
            "transcripts",
            "transcript_sha256",
            sha,
            columns,
            (text, dataset_name, entry_id, entry_index),
            columns,
        )
        return sha

    def upsert_reference_summary(self, text, transcript_sha, dataset_name, entry_id, entry_index):
        sha = summary_id(text)
        columns = (
            "summary_text",
            "transcript_sha256",
            "dataset_name",
            "entry_id",
            "entry_index",
        )
        self._upsert(
            "reference_summaries",
            "summary_sha256",
            sha,
            columns,
            (text, transcript_sha, dataset_name, entry_id, entry_index),
            columns,
        )
        return sha

    def upsert_model(self, model_bytes, name, model_path):
        sha = model_id(model_bytes)
        columns = ("name", "model_path")
        self._upsert(
            "models", "model_sha256", sha, columns, (name, model_path), columns
        )
        return sha

    def upsert_template(self, system_content, user_prefix, name):
        sha = template_id(system_content, user_prefix)
        columns = ("name", "system_content", "user_prefix")
        self._upsert(
            "prompt_templates",
            "template_sha256",
            sha,
            columns,
            (name, system_content, user_prefix),
            ("name",),
        )
        return sha

    def upsert_judge(
        self,
        model_name,
        gen_params,
        system_content,
        user_template,
        requires_reference,
        name,
        endpoint,
        api_key_env,
    ):
        sha = judge_id(
            model_name, gen_params, system_content, user_template, requires_reference
        )
        columns = (
            "name",
            "endpoint",
            "model_name",
            "gen_params",
            "system_content",
            "user_template",
            "requires_reference",
            "api_key_env",
        )
        values = (
            name,
            endpoint,
            model_name,
            canonical_json(gen_params),
            system_content,
            user_template,
            1 if requires_reference else 0,
            api_key_env,
        )
        self._upsert("judges", "judge_sha256", sha, columns, values, columns)
        return sha

    def upsert_generation(
        self, transcript_sha, model_sha, model_args, template_sha, gen_params, generation_text
    ):
        sha = generation_id(transcript_sha, model_sha, model_args, template_sha, gen_params)
        columns = (
            "generation_text",
            "transcript_sha256",
            "model_sha256",
            "model_args",
            "template_sha256",
            "gen_params",
        )
        values = (
            generation_text,
            transcript_sha,
            model_sha,
            canonical_json(model_args),
            template_sha,
            canonical_json(gen_params),
        )
        self._upsert(
            "generations", "generation_sha256", sha, columns, values, columns
        )
        return sha

    def upsert_judge_evaluation(
        self, judge_sha, generation_sha, reference_sha, factual_correctness, completeness, conciseness
    ):
        sha = judge_evaluation_id(judge_sha, generation_sha, reference_sha)
        columns = (
            "judge_sha256",
            "generation_sha256",
            "reference_summary_sha256",
            "factual_correctness",
            "completeness",
            "conciseness",
        )
        values = (
            judge_sha,
            generation_sha,
            reference_sha,
            factual_correctness,
            completeness,
            conciseness,
        )
        self._upsert(
            "judge_evaluations",
            "judge_evaluation_sha256",
            sha,
            columns,
            values,
            ("factual_correctness", "completeness", "conciseness"),
        )
        return sha

    def upsert_metric_evaluation(self, metric_name, generation_sha, reference_sha, value):
        sha = metric_evaluation_id(metric_name, generation_sha, reference_sha)
        columns = ("metric_name", "generation_sha256", "reference_summary_sha256", "value")
        self._upsert(
            "metric_evaluations",
            "metric_evaluation_sha256",
            sha,
            columns,
            (metric_name, generation_sha, reference_sha, value),
            ("value",),
        )
        return sha

    def table_counts(self):
        return [
            (
                table,
                self._execute(f"SELECT COUNT(*) FROM {table}", ()).fetchone()[0],
            )
            for table in TABLES
        ]

    def clear(self):
        deleted = 0
        with self._db:
            for table in reversed(TABLES):
                deleted += self._db.execute(f"DELETE FROM {table}").rowcount
        return deleted

    def close(self):
        self._db.close()
