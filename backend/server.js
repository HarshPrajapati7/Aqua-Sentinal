import express from "express";
import cors from "cors";
import Database from "better-sqlite3";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.resolve(__dirname, "../aqua_sentinel.db");
const db = new Database(dbPath, { fileMustExist: false });

const app = express();
app.use(cors());
app.use(express.json());
app.use("/outputs", express.static(path.resolve(__dirname, "../outputs")));

app.get("/api/health", (_req, res) => {
  res.json({ status: "ok", service: "Aqua-Sentinel Reader API" });
});

app.get("/api/runs", (_req, res) => {
  try {
    const runs = db.prepare(
      "SELECT * FROM runs ORDER BY id DESC LIMIT 100"
    ).all();
    res.json(runs);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get("/api/runs/:id", (req, res) => {
  try {
    const run = db.prepare("SELECT * FROM runs WHERE id = ?").get(
      req.params.id
    );
    if (!run) return res.status(404).json({ error: "Run not found" });
    const particles = db
      .prepare(
        "SELECT * FROM particles WHERE run_id = ? ORDER BY particle_index ASC"
      )
      .all(req.params.id);
    res.json({ run, particles });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get("/api/runs/:id/export.csv", (req, res) => {
  try {
    const run = db.prepare("SELECT * FROM runs WHERE id = ?").get(
      req.params.id
    );
    if (!run) return res.status(404).json({ error: "Run not found" });
    const particles = db
      .prepare("SELECT * FROM particles WHERE run_id = ?")
      .all(req.params.id);
    const header =
      "particle_index,equiv_diameter_um,major_axis_um,minor_axis_um,aspect_ratio,circularity,solidity,morphology";
    const rows = particles.map((particle) =>
      [
        particle.particle_index,
        particle.equiv_diameter_um,
        particle.major_axis_um,
        particle.minor_axis_um,
        particle.aspect_ratio,
        particle.circularity,
        particle.solidity,
        particle.morphology,
      ].join(",")
    );
    res.setHeader("Content-Type", "text/csv");
    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${run.sample_id}_particles.csv"`
    );
    res.send([header, ...rows].join("\n"));
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Aqua-Sentinel API listening on http://localhost:${PORT}`);
});
