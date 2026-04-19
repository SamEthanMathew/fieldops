import { useEffect, useRef, useCallback } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import type { AmbulanceRecord, HospitalRecord, IncidentSnapshot, PreHospitalNotification } from "../types";

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

const SCENE_LAT = 40.4350;
const SCENE_LNG = -79.9900;
const ANIM_DURATION = 900; // ms to interpolate between positions

function ambulanceColor(status: string): string {
  if (status === "AVAILABLE") return "#10b981";
  if (status === "EN_ROUTE" || status === "DISPATCHED") return "#f59e0b";
  if (status === "OUT_OF_SERVICE" || status === "CRITICAL") return "#ef4444";
  return "#64748b";
}

function hospitalStatusColor(status: string, divert: boolean): string {
  if (divert || status === "DIVERT" || status === "OUT_OF_SERVICE") return "#ef4444";
  if (status === "YELLOW" || status === "PARTIAL") return "#f59e0b";
  return "#10b981";
}

function makeAmbulanceIcon(ambulance: AmbulanceRecord) {
  const color = ambulanceColor(ambulance.status);
  const label = ambulance.ambulance_id.replace("A-", "");
  const isMoving = ambulance.status === "EN_ROUTE" || ambulance.status === "DISPATCHED";
  const size = isMoving ? 32 : 26;
  return L.divIcon({
    className: "",
    html: `<div style="
      width:${size}px;height:${size}px;border-radius:50%;
      background:${color};
      border:2px solid rgba(255,255,255,0.35);
      display:flex;align-items:center;justify-content:center;
      font-size:${isMoving ? 10 : 9}px;font-weight:800;color:white;
      box-shadow:0 0 ${isMoving ? 16 : 8}px ${color}${isMoving ? "bb" : "66"};
      font-family:Inter,sans-serif;
      transition:all 0.3s;
      position:relative;
    ">
      ${isMoving ? `<div style="position:absolute;inset:-4px;border-radius:50%;border:2px solid ${color};opacity:0.5;animation:amb-ring 1.2s ease-out infinite;"></div>` : ""}
      ${label}
    </div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function makeHospitalIcon(hospital: HospitalRecord, hasAlert: boolean) {
  const color = hospitalStatusColor(hospital.status, hospital.divert_status);
  const shortName = hospital.name
    .replace("UPMC ", "")
    .replace(" Hospital", "")
    .replace("Allegheny General", "AGH")
    .replace("St. Clair", "St.Clair")
    .replace("Jefferson", "Jeff");
  const loadPct = Math.round(hospital.current_load_pct * 100);
  const loadColor = loadPct > 85 ? "#ef4444" : loadPct > 60 ? "#f59e0b" : "#10b981";
  return L.divIcon({
    className: "",
    html: `<div style="
      padding:5px 8px 4px;border-radius:8px;
      background:rgba(6,13,27,0.97);
      border:1.5px solid ${color};
      box-shadow:0 0 14px ${color}44, 0 2px 8px rgba(0,0,0,0.5);
      font-family:Inter,sans-serif;
      min-width:88px;
      position:relative;
    ">
      ${hasAlert ? `<div style="position:absolute;top:-5px;right:-5px;width:12px;height:12px;border-radius:50%;background:#ef4444;box-shadow:0 0 8px #ef444488;animation:hosp-alert 0.8s ease-in-out infinite;"></div>` : ""}
      <div style="font-size:9px;font-weight:700;color:#f1f5f9;white-space:nowrap;">${shortName}</div>
      <div style="font-size:8px;color:${color};margin-top:1px;">Lvl ${hospital.trauma_level} | ${hospital.capacity.available_beds} beds</div>
      <div style="margin-top:3px;height:3px;border-radius:2px;background:rgba(255,255,255,0.1);overflow:hidden;">
        <div style="height:100%;width:${Math.min(loadPct, 100)}%;background:${loadColor};border-radius:2px;transition:width 0.5s;"></div>
      </div>
    </div>`,
    iconSize: [94, 42],
    iconAnchor: [47, 21],
  });
}

function makeSceneIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="position:relative;display:flex;align-items:center;justify-content:center;width:60px;height:44px;">
      <div style="position:absolute;width:40px;height:40px;border-radius:50%;background:rgba(239,68,68,0.12);animation:scene-outer 2s ease-out infinite;"></div>
      <div style="position:absolute;width:24px;height:24px;border-radius:50%;background:rgba(239,68,68,0.2);animation:scene-outer 2s ease-out 0.5s infinite;"></div>
      <div style="
        width:18px;height:18px;border-radius:50%;
        background:#ef4444;
        border:2.5px solid rgba(255,255,255,0.7);
        display:flex;align-items:center;justify-content:center;
        z-index:2;
        box-shadow:0 0 12px #ef4444aa;
      ">
        <div style="width:5px;height:5px;border-radius:50%;background:white;"></div>
      </div>
      <div style="
        position:absolute;top:-16px;left:50%;transform:translateX(-50%);
        background:#ef4444;
        color:white;font-size:7.5px;font-weight:800;
        padding:2px 6px;border-radius:3px;
        font-family:Inter,sans-serif;white-space:nowrap;
        letter-spacing:0.08em;
        box-shadow:0 2px 6px rgba(239,68,68,0.5);
      ">INCIDENT</div>
    </div>`,
    iconSize: [60, 44],
    iconAnchor: [30, 30],
  });
}

const LegendControl = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div");
    div.innerHTML = `
      <div style="
        background:rgba(6,13,27,0.97);
        border:1px solid #1e3a5f;
        border-radius:10px;
        padding:10px 12px;
        font-family:Inter,sans-serif;
        font-size:10px;
        color:#94a3b8;
        pointer-events:none;
        box-shadow:0 4px 20px rgba(0,0,0,0.5);
        min-width:130px;
      ">
        <div style="font-weight:800;color:#e2e8f0;margin-bottom:7px;font-size:10px;letter-spacing:0.1em;">LEGEND</div>
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:4px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#ef4444;box-shadow:0 0 6px #ef4444;flex-shrink:0;"></div>
          <span>Incident Scene</span>
        </div>
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:4px;">
          <div style="width:10px;height:10px;border-radius:2px;background:rgba(6,13,27,0.9);border:1.5px solid #10b981;flex-shrink:0;"></div>
          <span>Hospital</span>
        </div>
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:4px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#10b981;flex-shrink:0;"></div>
          <span>Available Unit</span>
        </div>
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:4px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#f59e0b;box-shadow:0 0 6px #f59e0b66;flex-shrink:0;"></div>
          <span>En Route</span>
        </div>
        <div style="display:flex;align-items:center;gap:7px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#ef4444;opacity:0.5;flex-shrink:0;"></div>
          <span>Out of Service</span>
        </div>
      </div>`;
    return div;
  },
});

// Ambulance count badge overlay
const AmbulanceBadge = L.Control.extend({
  onAdd() {
    const div = L.DomUtil.create("div");
    div.id = "amb-count-badge";
    div.innerHTML = "";
    return div;
  },
});

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
}

interface ImperativeLayersProps {
  snapshot: IncidentSnapshot;
  onHospitalClick: (id: string) => void;
  selectedHospitalId: string | null;
}

function ImperativeLayers({ snapshot, onHospitalClick, selectedHospitalId }: ImperativeLayersProps) {
  const map = useMap();

  // Refs for imperative marker management
  const ambulanceMarkersRef = useRef<Record<string, L.Marker>>({});
  const ambulancePositionsRef = useRef<Record<string, { lat: number; lng: number }>>({});
  const animFrameRef = useRef<number>(0);
  const animTargetsRef = useRef<Record<string, { fromLat: number; fromLng: number; toLat: number; toLng: number; startTime: number }>>({});
  const hospitalMarkersRef = useRef<Record<string, L.Marker>>({});
  const routeLinesRef = useRef<Record<string, L.Polyline>>({});
  const sceneMarkerRef = useRef<L.Marker | null>(null);
  const legendRef = useRef<L.Control | null>(null);

  // Animate ambulances smoothly
  const runAnimation = useCallback(() => {
    const now = performance.now();
    let anyActive = false;

    for (const [id, anim] of Object.entries(animTargetsRef.current)) {
      const marker = ambulanceMarkersRef.current[id];
      if (!marker) continue;
      const elapsed = now - anim.startTime;
      const t = Math.min(elapsed / ANIM_DURATION, 1);
      const easedT = easeInOut(t);
      const lat = anim.fromLat + (anim.toLat - anim.fromLat) * easedT;
      const lng = anim.fromLng + (anim.toLng - anim.fromLng) * easedT;
      marker.setLatLng([lat, lng]);
      if (t < 1) anyActive = true;
      else delete animTargetsRef.current[id];
    }

    if (anyActive) {
      animFrameRef.current = requestAnimationFrame(runAnimation);
    }
  }, []);

  // Scene marker (once)
  useEffect(() => {
    if (!sceneMarkerRef.current) {
      sceneMarkerRef.current = L.marker([SCENE_LAT, SCENE_LNG], { icon: makeSceneIcon(), zIndexOffset: 1000 })
        .bindPopup('<div style="font-family:Inter,sans-serif;color:#f1f5f9;min-width:150px"><strong style="color:#ef4444">INCIDENT SCENE</strong><br/><span style="font-size:11px;color:#94a3b8">Birmingham Bridge MCI</span></div>')
        .addTo(map);
    }
    if (!legendRef.current) {
      legendRef.current = new LegendControl({ position: "bottomright" });
      legendRef.current.addTo(map);
    }
    return () => {
      sceneMarkerRef.current?.remove();
      sceneMarkerRef.current = null;
      legendRef.current?.remove();
      legendRef.current = null;
    };
  }, [map]);

  // Hospital markers
  useEffect(() => {
    const hospitals = Object.values(snapshot.hospitals);
    const preNotifications: PreHospitalNotification[] = snapshot.pre_notifications ?? [];
    const currentIds = new Set(hospitals.map(h => h.hospital_id));

    // Remove stale
    for (const [id, marker] of Object.entries(hospitalMarkersRef.current)) {
      if (!currentIds.has(id)) { marker.remove(); delete hospitalMarkersRef.current[id]; }
    }

    // Add/update
    hospitals.forEach((hospital) => {
      const hasAlert = preNotifications.some(n => n.hospital_id === hospital.hospital_id);
      const isSelected = selectedHospitalId === hospital.hospital_id;
      const icon = makeHospitalIcon(hospital, hasAlert);

      const popupContent = `
        <div style="font-family:Inter,sans-serif;min-width:190px;color:#e2e8f0;">
          <div style="font-weight:700;color:#f1f5f9;font-size:13px;margin-bottom:6px;">${hospital.name}</div>
          <div style="font-size:11px;color:${hospitalStatusColor(hospital.status, hospital.divert_status)};margin-bottom:4px;font-weight:600;">
            ${hospital.divert_status ? "⛔ DIVERT" : hospital.status}
          </div>
          <div style="font-size:11px;color:#94a3b8;">Level ${hospital.trauma_level} Trauma Center</div>
          <div style="font-size:11px;color:#94a3b8;">Beds: ${hospital.capacity.available_beds}/${hospital.capacity.total_beds}</div>
          <div style="font-size:11px;color:#94a3b8;">ICU: ${hospital.capacity.icu_available} | OR: ${hospital.capacity.or_available}</div>
          <div style="font-size:11px;color:#94a3b8;">ETA from scene: ${hospital.eta_from_scene_minutes}min</div>
          ${hasAlert ? '<div style="font-size:11px;color:#f59e0b;margin-top:4px;font-weight:600;">⚠ Incoming pre-alert</div>' : ""}
          <div style="font-size:10px;color:#475569;margin-top:4px;">${hospital.specialties.join(", ")}</div>
        </div>`;

      if (hospitalMarkersRef.current[hospital.hospital_id]) {
        const m = hospitalMarkersRef.current[hospital.hospital_id];
        m.setIcon(icon);
        m.getPopup()?.setContent(popupContent);
        const el = m.getElement();
        if (el) {
          el.style.filter = isSelected ? "brightness(1.3)" : "brightness(1)";
          el.style.transform += isSelected ? " scale(1.05)" : "";
        }
      } else {
        const marker = L.marker([hospital.location.lat, hospital.location.lng], { icon, zIndexOffset: 500 })
          .bindPopup(popupContent, { className: "dark-popup" })
          .on("click", () => onHospitalClick(hospital.hospital_id))
          .addTo(map);
        hospitalMarkersRef.current[hospital.hospital_id] = marker;
      }
    });
  }, [snapshot.hospitals, snapshot.pre_notifications, selectedHospitalId, onHospitalClick, map]);

  // Route lines
  useEffect(() => {
    // Remove old lines
    for (const line of Object.values(routeLinesRef.current)) line.remove();
    routeLinesRef.current = {};

    const recentDispatches = snapshot.dispatches.filter(d => d.status === "EXECUTED" || d.status === "AWAITING_APPROVAL");
    recentDispatches.slice(-20).forEach((d) => {
      const hospital = snapshot.hospitals[d.destination_hospital];
      if (!hospital) return;
      const isExecuted = d.status === "EXECUTED";
      const color = isExecuted ? "#3b82f6" : "#f59e0b";
      const line = L.polyline(
        [[SCENE_LAT, SCENE_LNG], [hospital.location.lat, hospital.location.lng]],
        { color, weight: isExecuted ? 2 : 1.5, opacity: isExecuted ? 0.5 : 0.35, dashArray: isExecuted ? undefined : "6 5" }
      ).addTo(map);
      routeLinesRef.current[d.dispatch_id] = line;
    });
  }, [snapshot.dispatches, snapshot.hospitals, map]);

  // Ambulance markers with smooth animation
  useEffect(() => {
    const ambulances = Object.values(snapshot.ambulances);
    const currentIds = new Set(ambulances.map(a => a.ambulance_id));

    // Remove stale markers
    for (const [id, marker] of Object.entries(ambulanceMarkersRef.current)) {
      if (!currentIds.has(id)) {
        marker.remove();
        delete ambulanceMarkersRef.current[id];
        delete ambulancePositionsRef.current[id];
      }
    }

    ambulances.forEach((ambulance) => {
      const { lat, lng } = ambulance.position;
      const icon = makeAmbulanceIcon(ambulance);
      const popupContent = `
        <div style="font-family:Inter,sans-serif;min-width:160px;color:#e2e8f0;">
          <div style="font-weight:700;color:#f1f5f9;font-size:12px;margin-bottom:4px;">
            ${ambulance.ambulance_id} <span style="font-weight:400;color:#64748b;">(${ambulance.type})</span>
          </div>
          <div style="font-size:11px;color:${ambulanceColor(ambulance.status)};font-weight:600;">${ambulance.status}</div>
          ${ambulance.current_patient ? `<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Patient: ${ambulance.current_patient}</div>` : ""}
          ${ambulance.eta_available != null ? `<div style="font-size:11px;color:#64748b;">ETA available: ${ambulance.eta_available}min</div>` : ""}
        </div>`;

      if (ambulanceMarkersRef.current[ambulance.ambulance_id]) {
        // Update icon (for status changes)
        ambulanceMarkersRef.current[ambulance.ambulance_id].setIcon(icon);
        ambulanceMarkersRef.current[ambulance.ambulance_id].getPopup()?.setContent(popupContent);

        // Animate to new position if changed
        const prev = ambulancePositionsRef.current[ambulance.ambulance_id];
        if (prev && (Math.abs(prev.lat - lat) > 0.00001 || Math.abs(prev.lng - lng) > 0.00001)) {
          animTargetsRef.current[ambulance.ambulance_id] = {
            fromLat: prev.lat, fromLng: prev.lng,
            toLat: lat, toLng: lng,
            startTime: performance.now(),
          };
          cancelAnimationFrame(animFrameRef.current);
          animFrameRef.current = requestAnimationFrame(runAnimation);
        }
      } else {
        // Create new marker
        const marker = L.marker([lat, lng], { icon, zIndexOffset: 200 })
          .bindPopup(popupContent, { className: "dark-popup" })
          .addTo(map);
        ambulanceMarkersRef.current[ambulance.ambulance_id] = marker;
      }

      ambulancePositionsRef.current[ambulance.ambulance_id] = { lat, lng };
    });
  }, [snapshot.ambulances, map, runAnimation]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cancelAnimationFrame(animFrameRef.current);
      Object.values(ambulanceMarkersRef.current).forEach(m => m.remove());
      Object.values(hospitalMarkersRef.current).forEach(m => m.remove());
      Object.values(routeLinesRef.current).forEach(l => l.remove());
    };
  }, [map]);

  return null;
}

interface PittsburghMapProps {
  snapshot: IncidentSnapshot;
  onHospitalClick: (id: string) => void;
  selectedHospitalId: string | null;
}

export default function PittsburghMap({ snapshot, onHospitalClick, selectedHospitalId }: PittsburghMapProps) {
  return (
    <div style={{ height: "100%", width: "100%", position: "relative" }}>
      <style>{`
        @keyframes scene-outer {
          0% { transform: scale(0.5); opacity: 0.8; }
          100% { transform: scale(2.5); opacity: 0; }
        }
        @keyframes amb-ring {
          0% { transform: scale(1); opacity: 0.6; }
          100% { transform: scale(1.8); opacity: 0; }
        }
        @keyframes hosp-alert {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.75); }
        }
        .leaflet-container {
          height: 100%;
          width: 100%;
          border-radius: 12px;
          font-family: Inter, sans-serif;
          background: #060d1b;
        }
        .dark-popup .leaflet-popup-content-wrapper {
          background: rgba(6,13,27,0.98) !important;
          border: 1px solid #1e3a5f !important;
          border-radius: 10px !important;
          color: #e2e8f0 !important;
          box-shadow: 0 8px 32px rgba(0,0,0,0.7) !important;
        }
        .dark-popup .leaflet-popup-tip-container { display: none; }
        .leaflet-popup-content-wrapper {
          background: rgba(6,13,27,0.98) !important;
          border: 1px solid #1e3a5f !important;
          border-radius: 10px !important;
          color: #e2e8f0 !important;
          box-shadow: 0 8px 32px rgba(0,0,0,0.7) !important;
        }
        .leaflet-popup-tip { background: rgba(6,13,27,0.98) !important; }
        .leaflet-popup-close-button { color: #64748b !important; }
        .leaflet-control-zoom {
          border: 1px solid #1e3a5f !important;
          border-radius: 8px !important;
          overflow: hidden;
        }
        .leaflet-control-zoom a {
          background: rgba(6,13,27,0.95) !important;
          color: #94a3b8 !important;
          border-color: #1e3a5f !important;
        }
        .leaflet-control-zoom a:hover {
          background: #0f1e35 !important;
          color: #e2e8f0 !important;
        }
        .leaflet-control-attribution {
          background: rgba(6,13,27,0.8) !important;
          color: #475569 !important;
          font-size: 9px !important;
        }
        .leaflet-control-attribution a { color: #64748b !important; }
      `}</style>
      <MapContainer
        center={[SCENE_LAT, SCENE_LNG]}
        zoom={13}
        style={{ height: "100%", width: "100%", borderRadius: "12px" }}
        zoomControl={true}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
          maxZoom={19}
        />
        <ImperativeLayers
          snapshot={snapshot}
          onHospitalClick={onHospitalClick}
          selectedHospitalId={selectedHospitalId}
        />
      </MapContainer>
    </div>
  );
}
