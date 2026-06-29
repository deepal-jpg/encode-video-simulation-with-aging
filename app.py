from __future__ import annotations

import atexit
import secrets
import threading

from flask import Flask, jsonify, render_template, request, session

from scheduler import SchedulerEngine


class SimulationStore:
    def __init__(self, factory, shared_engine: SchedulerEngine | None = None) -> None:
        self._factory = factory
        self._shared_engine = shared_engine
        self._lock = threading.RLock()
        self._engines: dict[str, SchedulerEngine] = {}

    def get_engine(self, session_id: str) -> SchedulerEngine:
        if self._shared_engine is not None:
            return self._shared_engine

        with self._lock:
            if session_id not in self._engines:
                self._engines[session_id] = self._factory()
            return self._engines[session_id]

    def stop_all(self) -> None:
        if self._shared_engine is not None:
            self._shared_engine.stop()
            return

        with self._lock:
            engines = list(self._engines.values())
            self._engines.clear()

        for engine in engines:
            engine.stop()


def create_app(testing: bool = False, engine: SchedulerEngine | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = secrets.token_hex(24)
    app.config["TESTING"] = testing
    app.config["SESSION_COOKIE_NAME"] = "scheduler_private_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

    store = SimulationStore(
        factory=lambda: SchedulerEngine(autostart=not testing),
        shared_engine=engine,
    )
    app.config["ENGINE_STORE"] = store

    def get_engine_for_request() -> SchedulerEngine:
        simulation_id = session.get("simulation_id")
        if simulation_id is None:
            simulation_id = secrets.token_urlsafe(16)
            session["simulation_id"] = simulation_id
        return store.get_engine(simulation_id)

    @app.get("/")
    def index() -> str:
        get_engine_for_request()
        return render_template("index.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok", "mode": "private-session"}, 200

    @app.get("/api/state")
    def get_state():
        return jsonify(get_engine_for_request().snapshot())

    @app.post("/api/jobs")
    def create_job():
        scheduler_engine = get_engine_for_request()
        payload = request.get_json(silent=True) or request.form
        name = str(payload.get("name", "")).strip()
        burst_value = payload.get("burst_time", 0)
        try:
            burst_time = int(burst_value)
            job = scheduler_engine.add_job(name, burst_time)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify({"job": job.to_dict(), "state": scheduler_engine.snapshot()}), 201

    @app.post("/api/reset")
    def reset():
        scheduler_engine = get_engine_for_request()
        scheduler_engine.reset()
        return jsonify(scheduler_engine.snapshot())

    if not testing:
        atexit.register(store.stop_all)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
