import React, { useEffect, useState } from "react";

const API_BASE = "http://localhost:4000";
const QC_STYLES = {
  VALID: { bg: "#e6f6ec", color: "#146c3a" },
  WARNING: { bg: "#fff4e0", color: "#9a5b00" },
  INCONCLUSIVE: { bg: "#fdeaea", color: "#a61b1b" },
};

export default function App() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadRunDetail = async (id) => {
    const response = await fetch(`${API_BASE}/api/runs/${id}`);
    const data = await response.json();
    setSelected(data);
  };

  useEffect(() => {
    fetch(`${API_BASE}/api/runs`)
      .then((response) => response.json())
      .then((data) => {
        setRuns(Array.isArray(data) ? data : []);
        if (Array.isArray(data) && data.length > 0) {
          loadRunDetail(data[0].id);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const activeRun = selected?.run;
  const qcBadge = QC_STYLES[activeRun?.qc_status] || {
    bg: "#eee",
    color: "#333",
  };

  return (
    <div
      style={{
        fontFamily: "Inter, system-ui, sans-serif",
        maxWidth: 1120,
        margin: "0 auto",
        padding: 24,
        color: "#111827",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid #e5e7eb",
          paddingBottom: 16,
          marginBottom: 24,
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 24 }}>Aqua-Sentinel Reader</h1>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>
            Field Screening Dashboard for PFAS & Microplastics
            (SIH26252 - Team Star Busters)
          </p>
        </div>
        {activeRun && (
          <a
            href={`${API_BASE}/api/runs/${activeRun.id}/export.csv`}
            style={{
              padding: "8px 14px",
              background: "#111827",
              color: "#fff",
              borderRadius: 8,
              textDecoration: "none",
              fontSize: 14,
            }}
          >
            Export CSV
          </a>
        )}
      </header>

      {loading ? (
        <p>Loading field records...</p>
      ) : !activeRun ? (
        <p>
          No runs logged yet. Execute{" "}
          <code>
            python edge_pipeline/controller.py --simulate --sample-id AS-0001
            --cartridge-id LOT-01
          </code>{" "}
          to generate a test record.
        </p>
      ) : (
        <>
          <section
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 16,
              marginBottom: 24,
            }}
          >
            <MetricCard
              title="PFAS Concentration"
              value={`${activeRun.pfas_ppt} ppt`}
              detail={`Uncertainty: +/- ${activeRun.pfas_uncertainty_ppt} ppt`}
            />
            <MetricCard
              title="Microplastics"
              value={`${activeRun.mp_particles_per_liter} particles/L`}
              detail={`${activeRun.mp_total_count} detected | Mean ${activeRun.mp_mean_size_um} um (${activeRun.mp_dominant_morphology})`}
            />
            <div
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 16,
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  color: "#6b7280",
                  textTransform: "uppercase",
                }}
              >
                Quality Control
              </div>
              <div style={{ marginTop: 8 }}>
                <span
                  style={{
                    padding: "4px 10px",
                    borderRadius: 999,
                    fontSize: 13,
                    fontWeight: 600,
                    background: qcBadge.bg,
                    color: qcBadge.color,
                  }}
                >
                  {activeRun.qc_status}
                </span>
              </div>
              <div
                style={{ fontSize: 12, color: "#6b7280", marginTop: 8 }}
              >
                {activeRun.qc_notes}
              </div>
            </div>
            <div
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 16,
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  color: "#6b7280",
                  textTransform: "uppercase",
                }}
              >
                Confirmatory Lab Flag
              </div>
              <div style={{ fontSize: 14, marginTop: 8 }}>
                PFAS (LC-MS/MS):{" "}
                <strong>
                  {activeRun.lab_referral_pfas
                    ? "Recommended"
                    : "Not Flagged"}
                </strong>
              </div>
              <div style={{ fontSize: 14, marginTop: 4 }}>
                Particles (Raman/FTIR):{" "}
                <strong>
                  {activeRun.lab_referral_mp
                    ? "Recommended"
                    : "Not Flagged"}
                </strong>
              </div>
            </div>
          </section>

          <section
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 16,
              marginBottom: 24,
            }}
          >
            <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>
              Sample Metadata: {activeRun.sample_id}
            </h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 12,
                fontSize: 14,
              }}
            >
              <div><strong>Source:</strong> {activeRun.source_type}</div>
              <div><strong>Location:</strong> {activeRun.location_name}</div>
              <div><strong>Volume:</strong> {activeRun.volume_ml} mL</div>
              <div><strong>Cartridge ID:</strong> {activeRun.cartridge_id}</div>
              <div>
                <strong>Blank Verified:</strong>{" "}
                {activeRun.blank_verified ? "Yes" : "No"}
              </div>
              <div>
                <strong>Timestamp:</strong>{" "}
                {new Date(activeRun.timestamp_utc).toLocaleString()}
              </div>
            </div>
          </section>

          <section
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 16,
            }}
          >
            <h2 style={{ margin: "0 0 12px", fontSize: 16 }}>
              Traceable Sample History
            </h2>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 14,
              }}
            >
              <thead>
                <tr
                  style={{
                    textAlign: "left",
                    borderBottom: "1px solid #e5e7eb",
                    color: "#6b7280",
                  }}
                >
                  <th style={{ padding: 8 }}>Sample ID</th>
                  <th style={{ padding: 8 }}>Source</th>
                  <th style={{ padding: 8 }}>Cartridge</th>
                  <th style={{ padding: 8 }}>PFAS (ppt)</th>
                  <th style={{ padding: 8 }}>Microplastics (/L)</th>
                  <th style={{ padding: 8 }}>QC</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => loadRunDetail(run.id)}
                    style={{
                      cursor: "pointer",
                      borderBottom: "1px solid #f3f4f6",
                      background:
                        run.id === activeRun.id ? "#f9fafb" : "transparent",
                    }}
                  >
                    <td style={{ padding: 8, fontWeight: 600 }}>
                      {run.sample_id}
                    </td>
                    <td style={{ padding: 8 }}>{run.source_type}</td>
                    <td style={{ padding: 8 }}>{run.cartridge_id}</td>
                    <td style={{ padding: 8 }}>{run.pfas_ppt}</td>
                    <td style={{ padding: 8 }}>
                      {run.mp_particles_per_liter}
                    </td>
                    <td style={{ padding: 8 }}>{run.qc_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

function MetricCard({ title, value, detail }) {
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: 16,
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: "#6b7280",
          textTransform: "uppercase",
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, marginTop: 6 }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: "#6b7280" }}>{detail}</div>
    </div>
  );
}
