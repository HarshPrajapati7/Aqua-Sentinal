import sqlite3
from pathlib import Path
from typing import Any, Dict, List

DB_PATH = Path(__file__).resolve().parent.parent / "aqua_sentinel.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id TEXT UNIQUE NOT NULL,
                timestamp_utc TEXT NOT NULL,
                source_type TEXT NOT NULL,
                location_name TEXT,
                latitude REAL,
                longitude REAL,
                volume_ml REAL NOT NULL,
                cartridge_id TEXT NOT NULL,
                blank_verified INTEGER NOT NULL DEFAULT 0,
                blank_mv REAL,
                calibration_px_per_um REAL NOT NULL,
                pfas_ppt REAL,
                pfas_uncertainty_ppt REAL,
                mp_total_count INTEGER NOT NULL DEFAULT 0,
                mp_particles_per_liter REAL NOT NULL DEFAULT 0.0,
                mp_mean_size_um REAL,
                mp_dominant_morphology TEXT,
                qc_status TEXT NOT NULL,
                qc_notes TEXT,
                lab_referral_pfas INTEGER NOT NULL DEFAULT 0,
                lab_referral_mp INTEGER NOT NULL DEFAULT 0,
                annotated_image_path TEXT
            );

            CREATE TABLE IF NOT EXISTS particles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                particle_index INTEGER NOT NULL,
                equiv_diameter_um REAL NOT NULL,
                major_axis_um REAL NOT NULL,
                minor_axis_um REAL NOT NULL,
                aspect_ratio REAL NOT NULL,
                circularity REAL NOT NULL,
                solidity REAL NOT NULL,
                morphology TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )


def insert_run(
    run_data: Dict[str, Any],
    particles: List[Dict[str, Any]],
    db_path: Path = DB_PATH,
) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (
                sample_id, timestamp_utc, source_type, location_name,
                latitude, longitude, volume_ml, cartridge_id,
                blank_verified, blank_mv, calibration_px_per_um,
                pfas_ppt, pfas_uncertainty_ppt,
                mp_total_count, mp_particles_per_liter,
                mp_mean_size_um, mp_dominant_morphology,
                qc_status, qc_notes,
                lab_referral_pfas, lab_referral_mp,
                annotated_image_path
            ) VALUES (
                :sample_id, :timestamp_utc, :source_type, :location_name,
                :latitude, :longitude, :volume_ml, :cartridge_id,
                :blank_verified, :blank_mv, :calibration_px_per_um,
                :pfas_ppt, :pfas_uncertainty_ppt,
                :mp_total_count, :mp_particles_per_liter,
                :mp_mean_size_um, :mp_dominant_morphology,
                :qc_status, :qc_notes,
                :lab_referral_pfas, :lab_referral_mp,
                :annotated_image_path
            )
            """,
            run_data,
        )
        run_id = cur.lastrowid
        if particles:
            conn.executemany(
                """
                INSERT INTO particles (
                    run_id, particle_index, equiv_diameter_um,
                    major_axis_um, minor_axis_um, aspect_ratio,
                    circularity, solidity, morphology
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        p["idx"],
                        p["equiv_diameter_um"],
                        p["major_axis_um"],
                        p["minor_axis_um"],
                        p["aspect_ratio"],
                        p["circularity"],
                        p["solidity"],
                        p["morphology"],
                    )
                    for p in particles
                ],
            )
        return int(run_id)


def list_runs(limit: int = 50, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
