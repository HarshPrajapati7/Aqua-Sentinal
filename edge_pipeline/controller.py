import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
import serial

from database import init_db, insert_run
from microplastic_analyzer import analyze_membrane_image


PFAS_LAB_REFERRAL_PPT = 4.0
MP_LAB_REFERRAL_PER_L = 100.0
MAX_FILTER_LOADING = 0.35


class HardwareBridge:
    def __init__(
        self, port: Optional[str], baud: int = 115200, simulate: bool = False
    ):
        self.simulate = simulate
        self.ser = None if simulate else serial.Serial(port, baud, timeout=5)
        if self.ser:
            time.sleep(2.0)

    def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.simulate:
            return self._simulate_response(payload)
        raw = json.dumps(payload) + "\n"
        self.ser.write(raw.encode("utf-8"))
        line = self.ser.readline().decode("utf-8").strip()
        if not line:
            raise TimeoutError(
                f"No response from ESP32-S3 for command: {payload.get('cmd')}"
            )
        return json.loads(line)

    def _simulate_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cmd = payload.get("cmd")
        if cmd == "PING":
            return {
                "ok": True,
                "device": "Aqua-Sentinel-SIM",
                "ads_ready": True,
                "battery_v": 11.9,
            }
        if cmd == "SET_CARTRIDGE":
            return {"ok": True, "cartridge_id": payload.get("cartridge_id")}
        if cmd == "RUN_BLANK":
            return {
                "ok": True,
                "blank_mv": 12.4,
                "noise_std_mv": 0.9,
                "blank_verified": True,
            }
        if cmd == "START_PUMP":
            return {
                "ok": True,
                "volume_ml": payload.get("volume_ml", 500.0),
                "estimated_ms": 500,
            }
        if cmd == "SET_LED":
            return {"ok": True, "led_pwm": payload.get("pwm", 180)}
        if cmd == "READ_PFAS":
            return {
                "ok": True,
                "raw_mv": 26.8,
                "net_mv": 14.4,
                "noise_std_mv": 1.1,
                "pfas_ppt": 12.24,
                "uncertainty_ppt": 1.87,
                "qc_status": "VALID",
                "blank_verified": True,
            }
        return {"ok": True}

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()


def capture_frame(
    camera_index: int = 0, simulate: bool = False
) -> np.ndarray:
    if simulate:
        image = np.full((600, 800, 3), 235, dtype=np.uint8)
        rng = np.random.default_rng(42)
        for _ in range(18):
            cx = int(rng.integers(60, 740))
            cy = int(rng.integers(60, 540))
            radius = int(rng.integers(4, 16))
            cv2.circle(image, (cx, cy), radius, (55, 60, 70), -1)
        for _ in range(5):
            x1 = int(rng.integers(80, 680))
            y1 = int(rng.integers(80, 480))
            cv2.line(
                image,
                (x1, y1),
                (x1 + 55, y1 + 12),
                (40, 45, 55),
                3,
            )
        return image

    camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        raise RuntimeError(
            f"Unable to open microscope camera at index {camera_index}"
        )
    for _ in range(10):
        camera.read()
    ok, frame = camera.read()
    camera.release()
    if not ok or frame is None:
        raise RuntimeError("Failed to capture frame from microscope camera.")
    return frame


def run_screening(args: argparse.Namespace) -> None:
    init_db()
    hardware = HardwareBridge(
        port=args.port, simulate=args.simulate
    )

    try:
        ping = hardware.send({"cmd": "PING"})
        if not ping.get("ok"):
            raise RuntimeError("ESP32-S3 failed health check.")

        hardware.send(
            {"cmd": "SET_CARTRIDGE", "cartridge_id": args.cartridge_id}
        )
        blank = hardware.send({"cmd": "RUN_BLANK"})
        blank_ok = bool(blank.get("blank_verified", False))
        blank_mv = blank.get("blank_mv")

        pump = hardware.send(
            {
                "cmd": "START_PUMP",
                "volume_ml": args.volume_ml,
                "pwm": 200,
            }
        )
        if not args.simulate:
            wait_seconds = pump.get("estimated_ms", 5000) / 1000.0 + 1.0
            time.sleep(wait_seconds)

        pfas = hardware.send({"cmd": "READ_PFAS"})
        pfas_ppt = float(pfas.get("pfas_ppt", 0.0))
        pfas_unc = float(pfas.get("uncertainty_ppt", 0.0))

        hardware.send({"cmd": "SET_LED", "pwm": 200})
        time.sleep(0.3)
        frame = capture_frame(
            camera_index=args.camera, simulate=args.simulate
        )
        hardware.send({"cmd": "SET_LED", "pwm": 0})

        output_dir = Path("outputs")
        image_path = output_dir / f"{args.sample_id}_annotated.png"
        microplastics = analyze_membrane_image(
            image_bgr=frame,
            volume_ml=args.volume_ml,
            px_per_um=args.px_per_um,
            output_annotated_path=image_path,
        )

        qc_notes = []
        qc_status = "VALID"
        if not blank_ok:
            qc_status = "INCONCLUSIVE"
            qc_notes.append("Field/equipment blank failed stability check.")
        if (
            pfas.get("qc_status") == "WARNING"
            and qc_status != "INCONCLUSIVE"
        ):
            qc_status = "WARNING"
            qc_notes.append("Elevated PFAS electrochemical baseline noise.")
        if microplastics["filter_loading_ratio"] > MAX_FILTER_LOADING:
            qc_status = "WARNING" if qc_status == "VALID" else qc_status
            qc_notes.append(
                "High membrane loading ratio; possible particle overlap or clogging."
            )

        lab_referral_pfas = (
            1 if pfas_ppt >= PFAS_LAB_REFERRAL_PPT else 0
        )
        lab_referral_mp = (
            1
            if microplastics["particles_per_liter"]
            >= MP_LAB_REFERRAL_PER_L
            else 0
        )

        run_record = {
            "sample_id": args.sample_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source_type": args.source_type,
            "location_name": args.location,
            "latitude": args.lat,
            "longitude": args.lon,
            "volume_ml": args.volume_ml,
            "cartridge_id": args.cartridge_id,
            "blank_verified": 1 if blank_ok else 0,
            "blank_mv": blank_mv,
            "calibration_px_per_um": args.px_per_um,
            "pfas_ppt": round(pfas_ppt, 2),
            "pfas_uncertainty_ppt": round(pfas_unc, 2),
            "mp_total_count": microplastics["total_count"],
            "mp_particles_per_liter": microplastics[
                "particles_per_liter"
            ],
            "mp_mean_size_um": microplastics["mean_size_um"],
            "mp_dominant_morphology": microplastics[
                "dominant_morphology"
            ],
            "qc_status": qc_status,
            "qc_notes": (
                "; ".join(qc_notes)
                if qc_notes
                else "All QC checks passed."
            ),
            "lab_referral_pfas": lab_referral_pfas,
            "lab_referral_mp": lab_referral_mp,
            "annotated_image_path": str(image_path),
        }
        run_id = insert_run(run_record, microplastics["particles"])

        report = {
            "run_id": run_id,
            "run": run_record,
            "microplastics_summary": {
                "size_histogram": microplastics["size_histogram"],
                "morphology_breakdown": microplastics[
                    "morphology_breakdown"
                ],
                "filter_loading_ratio": microplastics[
                    "filter_loading_ratio"
                ],
            },
        }
        report_path = output_dir / f"{args.sample_id}_report.json"
        report_path.write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
    finally:
        hardware.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Aqua-Sentinel Field Screening Controller"
    )
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--cartridge-id", required=True)
    parser.add_argument(
        "--source-type",
        default="Tap Water",
        choices=[
            "Tap Water",
            "River/Lake",
            "Groundwater",
            "Treatment Plant",
            "Industrial/Other",
        ],
    )
    parser.add_argument("--location", default="Field Site A")
    parser.add_argument("--lat", type=float, default=26.8467)
    parser.add_argument("--lon", type=float, default=80.9462)
    parser.add_argument("--volume-ml", type=float, default=500.0)
    parser.add_argument("--px-per-um", type=float, default=0.8)
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run without physical hardware",
    )
    run_screening(parser.parse_args())
