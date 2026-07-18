"""SQLite event store and replay adapter for the deterministic mind core."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from life_mind.domain import MindEvent, SimulationTrace, to_plain
from life_mind.simulator import HeadlessMindSimulator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentMindRuntime:
    """Persist domain events and rebuild the same mind by replaying them."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        seed: int = 20260717,
        legacy_seed: dict[str, float] | None = None,
    ) -> None:
        self.connection = connection
        self.replay_errors: list[str] = []
        self._create_schema()
        stored_seed = self._meta_get("mind_seed")
        if stored_seed is None:
            self.seed = int(seed)
            self._meta_set("mind_seed", self.seed)
        else:
            self.seed = int(stored_seed)
        bootstrap = self._meta_get("bootstrap_state")
        if bootstrap is None:
            bootstrap = legacy_seed or {"energy": 0.76, "mood": 0.59, "trust": 0.62}
            self._meta_set("bootstrap_state", bootstrap)
        self.bootstrap = dict(bootstrap)
        self.connection.commit()
        self.events = self._load_events()
        self.simulator = self._build_simulator(self.events)
        self._event_traces = {
            event.event_id: trace
            for event, trace in zip(self.events, self.simulator.traces, strict=True)
        }

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS mind_runtime_meta (
                meta_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mind_events_v2 (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mind_events_v2_created
                ON mind_events_v2(sequence);
            """
        )

    def _meta_get(self, key: str) -> Any:
        row = self.connection.execute(
            "SELECT value_json FROM mind_runtime_meta WHERE meta_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            self.replay_errors.append(f"元数据 {key} 无法解析")
            return None

    def _meta_set(self, key: str, value: Any) -> None:
        self.connection.execute(
            """
            INSERT INTO mind_runtime_meta(meta_key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(meta_key) DO UPDATE SET
                value_json=excluded.value_json,
                updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False, sort_keys=True), utc_now()),
        )

    def _load_events(self) -> list[MindEvent]:
        rows = self.connection.execute(
            "SELECT sequence, event_json FROM mind_events_v2 ORDER BY sequence"
        ).fetchall()
        events: list[MindEvent] = []
        for row in rows:
            try:
                payload = json.loads(row["event_json"])
                events.append(MindEvent.from_dict(payload, int(row["sequence"])))
            except (KeyError, TypeError, ValueError) as error:
                self.replay_errors.append(f"事件序号 {row['sequence']} 无法回放：{error}")
        return events

    def _new_simulator(self) -> HeadlessMindSimulator:
        simulator = HeadlessMindSimulator(self.seed)
        energy = max(0.0, min(1.0, float(self.bootstrap.get("energy", 0.76))))
        mood = max(0.0, min(1.0, float(self.bootstrap.get("mood", 0.59))))
        trust = max(0.0, min(1.0, float(self.bootstrap.get("trust", 0.62))))
        simulator.state.body.energy = energy
        simulator.state.body.fatigue = max(0.10, min(0.90, 1.0 - energy))
        simulator.state.affect.valence = mood * 2.0 - 1.0
        user = simulator.state.relations["user"]
        user.trust_goodwill = trust
        user.safety = trust
        user.respect = max(user.respect, trust)
        simulator.state.normalize()
        return simulator

    def _build_simulator(self, events: list[MindEvent]) -> HeadlessMindSimulator:
        simulator = self._new_simulator()
        simulator.run(events)
        return simulator

    def apply(self, event: MindEvent) -> SimulationTrace:
        existing = self._event_traces.get(event.event_id)
        if existing is not None:
            return existing

        # The normal path is incremental. Replaying the complete history for
        # every new event made n events cost O(n²), which becomes visible after
        # only a few hundred desktop interactions. If persistence fails, rebuild
        # from the last committed event list so memory and SQLite stay aligned.
        try:
            trace = self.simulator.apply_event(event)
            self.connection.execute(
                """
                INSERT INTO mind_events_v2(event_id, event_json, trace_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    json.dumps(to_plain(event), ensure_ascii=False, sort_keys=True),
                    json.dumps(to_plain(trace), ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            )
            self._meta_set("last_state", self.simulator.state.to_dict())
            self.connection.commit()
        except BaseException:
            try:
                self.connection.rollback()
            except sqlite3.Error:
                pass
            self.simulator = self._build_simulator(self.events)
            self._event_traces = {
                item.event_id: item_trace
                for item, item_trace in zip(
                    self.events, self.simulator.traces, strict=True
                )
            }
            raise
        self.events.append(event)
        self._event_traces[event.event_id] = trace
        return trace

    def redact_events(self, event_ids: set[str] | list[str] | tuple[str, ...]) -> int:
        """Remove private event text while keeping a replayable structural audit trail."""

        requested = {str(event_id) for event_id in event_ids if str(event_id).strip()}
        if not requested:
            return 0
        placeholders = ",".join("?" for _ in requested)
        rows = self.connection.execute(
            f"SELECT event_id, event_json, trace_json FROM mind_events_v2 "
            f"WHERE event_id IN ({placeholders})",
            tuple(sorted(requested)),
        ).fetchall()
        changed = 0
        for row in rows:
            try:
                event_payload = json.loads(row["event_json"])
                trace_payload = json.loads(row["trace_json"])
            except (TypeError, ValueError):
                self.replay_errors.append(f"事件 {row['event_id']} 的隐私清理失败：无法解析")
                continue
            metadata = dict(event_payload.get("metadata", {}))
            metadata["private_content_redacted"] = True
            event_payload.update(
                {
                    "content": "[已删除的私人内容]",
                    "source": "redacted_private_event",
                    "allowed_uses": ["state_update"],
                    "metadata": metadata,
                }
            )
            trace_payload["event"] = dict(event_payload)
            notes = list(trace_payload.get("notes", []))
            if "private_content_redacted" not in notes:
                notes.append("private_content_redacted")
            trace_payload["notes"] = notes
            self.connection.execute(
                "UPDATE mind_events_v2 SET event_json=?, trace_json=? WHERE event_id=?",
                (
                    json.dumps(event_payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(trace_payload, ensure_ascii=False, sort_keys=True),
                    row["event_id"],
                ),
            )
            changed += 1
        if changed:
            self.events = self._load_events()
            self.simulator = self._build_simulator(self.events)
            self._event_traces = {
                event.event_id: trace
                for event, trace in zip(
                    self.events, self.simulator.traces, strict=True
                )
            }
            self._meta_set("last_state", self.simulator.state.to_dict())
            self.connection.commit()
        return changed

    @property
    def state(self):
        return self.simulator.state

    @property
    def last_trace(self) -> SimulationTrace | None:
        return self.simulator.traces[-1] if self.simulator.traces else None

    def event_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM mind_events_v2").fetchone()
        return int(row[0])

    def recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT trace_json FROM mind_events_v2 ORDER BY sequence DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        traces: list[dict[str, Any]] = []
        for row in reversed(rows):
            try:
                traces.append(json.loads(row["trace_json"]))
            except (TypeError, ValueError):
                continue
        return traces

    def traces_since_days(
        self, days: float = 7.0, *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return replay traces inside a real-time review window, oldest first."""

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        cutoff = (current.astimezone(timezone.utc) - timedelta(days=max(0.0, days))).isoformat()
        rows = self.connection.execute(
            "SELECT trace_json FROM mind_events_v2 WHERE created_at>=? ORDER BY sequence",
            (cutoff,),
        ).fetchall()
        traces: list[dict[str, Any]] = []
        for row in rows:
            try:
                traces.append(json.loads(row["trace_json"]))
            except (TypeError, ValueError):
                continue
        return traces

    def debug_snapshot(self, limit: int = 20) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "event_count": self.event_count(),
            "state": self.state.to_dict(),
            "last_trace": to_plain(self.last_trace) if self.last_trace else None,
            "recent_traces": self.recent_traces(limit),
            "replay_errors": list(self.replay_errors),
        }


__all__ = ("PersistentMindRuntime",)
